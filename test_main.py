import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock, call

# Assuming main.py is in the same directory or accessible in PYTHONPATH
import main # To allow patching main.call_agent_async and accessing main.types
from google.genai import types as genai_types # For type hinting if needed, but we mock main.types

# Helper function to create an async generator mock for runner.run_async
async def create_async_event_stream(*events_or_errors):
    for item in events_or_errors:
        await asyncio.sleep(0) # Ensure the generator yields control
        if isinstance(item, Exception):
            raise item
        # Simulate the event structure ADK uses
        event_mock = MagicMock(spec=genai_types.Event) # Use spec for better mocking
        event_mock.is_final_response.return_value = True
        event_mock.content = MagicMock(spec=genai_types.Content)
        # Ensure parts is a list, even if empty
        event_mock.content.parts = [MagicMock(spec=genai_types.Part, text=item if isinstance(item, str) else "")] 
        if isinstance(item, str):
             event_mock.content.parts[0].text = item
        else: # Handle escalation or other non-string final responses if necessary
            event_mock.content.parts = []


        event_mock.actions = MagicMock()
        event_mock.actions.escalate = None # Default to no escalation
        event_mock.error_message = None

        # Handle escalation scenario for tests
        if isinstance(item, tuple) and item[0] == "escalate":
            event_mock.actions.escalate = True
            event_mock.error_message = item[1]
            event_mock.content = None # Escalation usually means no content

        yield event_mock

class TestCallAgentAsync(unittest.IsolatedAsyncioTestCase):

    # Patch main.types to control Content and Part object creation within call_agent_async
    @patch('main.types') 
    async def test_scenario1_initial_call_succeeds(self, mock_main_types):
        # Configure the mock for main.types.Content and main.types.Part
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async, \
             patch.dict('main.active_sessions', {}, clear=True) as mock_active_sessions_dict:

            mock_get_session.return_value = "session_user1_valid"
            mock_run_async.return_value = create_async_event_stream("Call successful")

            response = await main.call_agent_async("hello", "user1")

            self.assertEqual(response, "Call successful")
            mock_get_session.assert_called_once_with("user1")
            mock_run_async.assert_called_once()
            _, kwargs = mock_run_async.call_args
            self.assertEqual(kwargs.get('user_id'), "user1")
            self.assertEqual(kwargs.get('session_id'), "session_user1_valid")
            # Check that Content was called by call_agent_async
            mock_main_types.Content.assert_called_once_with(role="user", parts=[mock_main_types.Part.return_value])
            mock_main_types.Part.assert_called_once_with(text="hello")
            # active_sessions.pop should not have been called
            self.assertNotIn("user1", mock_active_sessions_dict) # or check that pop wasn't called if we mock it directly

    @patch('main.types')
    async def test_scenario2_session_not_found_retry_succeeds(self, mock_main_types):
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async, \
             patch.dict('main.active_sessions', {"user1": "session_user1_old"}, clear=True) as mock_active_sessions_dict:
            
            mock_get_session.side_effect = ["session_user1_old", "session_user1_new"]

            async def run_async_side_effect(*args, **kwargs):
                session_id = kwargs.get('session_id')
                if session_id == "session_user1_old":
                    # This makes it an async generator that raises
                    async for _ in create_async_event_stream(ValueError("Session not found: session_user1_old")): pass
                elif session_id == "session_user1_new":
                    async for event in create_async_event_stream("Retry successful"):
                        yield event
                else:
                    raise AssertionError(f"Unexpected session_id: {session_id}")
            
            mock_run_async.side_effect = run_async_side_effect

            response = await main.call_agent_async("hello", "user1")

            self.assertEqual(response, "Retry successful")
            self.assertEqual(mock_get_session.call_count, 2)
            mock_get_session.assert_has_calls([call("user1"), call("user1")])
            # Check active_sessions.pop was effectively called by checking the dict
            self.assertNotIn("session_user1_old", mock_active_sessions_dict.values()) # old session should be gone
            # Check that run_async was called twice with the correct session IDs
            self.assertEqual(mock_run_async.call_count, 2)
            first_call_args, first_call_kwargs = mock_run_async.call_args_list[0]
            second_call_args, second_call_kwargs = mock_run_async.call_args_list[1]
            self.assertEqual(first_call_kwargs.get('session_id'), "session_user1_old")
            self.assertEqual(second_call_kwargs.get('session_id'), "session_user1_new")


    @patch('main.types')
    async def test_scenario3_session_not_found_retry_fails_other_error(self, mock_main_types):
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async, \
             patch.dict('main.active_sessions', {"user1": "session_user1_old"}, clear=True) as mock_active_sessions_dict:

            mock_get_session.side_effect = ["session_user1_old", "session_user1_new"]

            async def run_async_side_effect(*args, **kwargs):
                session_id = kwargs.get('session_id')
                if session_id == "session_user1_old":
                    async for _ in create_async_event_stream(ValueError("Session not found: session_user1_old")): pass
                elif session_id == "session_user1_new":
                    async for _ in create_async_event_stream(RuntimeError("Retry failed")): pass
                else:
                    raise AssertionError(f"Unexpected session_id: {session_id}")
            
            mock_run_async.side_effect = run_async_side_effect
            
            response = await main.call_agent_async("hello", "user1")

            self.assertEqual(response, "Sorry, I encountered an error after a session issue: Retry failed")
            self.assertEqual(mock_get_session.call_count, 2)
            self.assertEqual(mock_run_async.call_count, 2)

    @patch('main.types')
    async def test_scenario4_session_not_found_retry_fails_session_not_found(self, mock_main_types):
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async, \
             patch.dict('main.active_sessions', {"user1": "session_user1_old"}, clear=True) as mock_active_sessions_dict:

            mock_get_session.side_effect = ["session_user1_old", "session_user1_new"]

            async def run_async_side_effect(*args, **kwargs):
                session_id = kwargs.get('session_id')
                if session_id == "session_user1_old":
                    async for _ in create_async_event_stream(ValueError("Session not found: session_user1_old")): pass
                elif session_id == "session_user1_new":
                    async for _ in create_async_event_stream(ValueError("Session not found: session_user1_new")): pass # Error on retry
                else:
                    raise AssertionError(f"Unexpected session_id: {session_id}")
            
            mock_run_async.side_effect = run_async_side_effect
            
            response = await main.call_agent_async("hello", "user1")

            self.assertEqual(response, "Sorry, I encountered an error after a session issue: Session not found: session_user1_new")
            self.assertEqual(mock_get_session.call_count, 2)
            self.assertEqual(mock_run_async.call_count, 2)

    @patch('main.types')
    async def test_scenario5_non_session_not_found_value_error(self, mock_main_types):
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async, \
             patch.dict('main.active_sessions', {}, clear=True) as mock_active_sessions_dict:

            mock_get_session.return_value = "session_user1_valid"
            
            async def run_async_side_effect(*args, **kwargs):
                async for _ in create_async_event_stream(ValueError("Some other value error")): pass
            mock_run_async.side_effect = run_async_side_effect

            response = await main.call_agent_async("hello", "user1")

            self.assertEqual(response, "Sorry, I encountered an error: Some other value error")
            mock_get_session.assert_called_once_with("user1")
            mock_run_async.assert_called_once()
            # active_sessions.pop should not be called in this case
            # We can verify this by checking that get_or_create_session was only called once.
            self.assertEqual(mock_get_session.call_count, 1)


    @patch('main.types')
    async def test_scenario6_unexpected_non_value_error(self, mock_main_types):
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async, \
             patch.dict('main.active_sessions', {}, clear=True) as mock_active_sessions_dict:

            mock_get_session.return_value = "session_user1_valid"
            
            async def run_async_side_effect(*args, **kwargs):
                async for _ in create_async_event_stream(TypeError("Some type error")): pass
            mock_run_async.side_effect = run_async_side_effect

            response = await main.call_agent_async("hello", "user1")

            self.assertEqual(response, "Sorry, an unexpected error occurred: Some type error")
            mock_get_session.assert_called_once_with("user1")
            mock_run_async.assert_called_once()
            self.assertEqual(mock_get_session.call_count, 1)

    @patch('main.types')
    async def test_escalation_event_initial_call(self, mock_main_types):
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async:
            
            mock_get_session.return_value = "session_user1_valid"
            # Simulate an escalation event
            mock_run_async.return_value = create_async_event_stream(("escalate", "Escalation message here"))

            response = await main.call_agent_async("hello", "user1")

            self.assertEqual(response, "Agent escalated: Escalation message here")
            mock_get_session.assert_called_once_with("user1")
            mock_run_async.assert_called_once()

    @patch('main.types')
    async def test_escalation_event_on_retry(self, mock_main_types):
        mock_main_types.Content = MagicMock(return_value=MagicMock(spec=genai_types.Content))
        mock_main_types.Part = MagicMock(return_value=MagicMock(spec=genai_types.Part))

        with patch('main.get_or_create_session') as mock_get_session, \
             patch('main.runner.run_async') as mock_run_async, \
             patch.dict('main.active_sessions', {"user1": "session_user1_old"}, clear=True) as mock_active_sessions_dict:

            mock_get_session.side_effect = ["session_user1_old", "session_user1_new"]

            async def run_async_side_effect(*args, **kwargs):
                session_id = kwargs.get('session_id')
                if session_id == "session_user1_old":
                    async for _ in create_async_event_stream(ValueError("Session not found: session_user1_old")): pass
                elif session_id == "session_user1_new":
                    # Simulate escalation on retry
                    async for event in create_async_event_stream(("escalate", "Escalation on retry")):
                        yield event
                else:
                    raise AssertionError(f"Unexpected session_id: {session_id}")
            
            mock_run_async.side_effect = run_async_side_effect

            response = await main.call_agent_async("hello", "user1")
            self.assertEqual(response, "Agent escalated on retry: Escalation on retry")
            self.assertEqual(mock_get_session.call_count, 2)
            self.assertEqual(mock_run_async.call_count, 2)


if __name__ == '__main__':
    unittest.main()
