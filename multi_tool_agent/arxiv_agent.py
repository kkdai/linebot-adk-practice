import arxiv
import re

# Common English stop words
STOP_WORDS = set([
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "can", "could", "may", "might", "must", "and", "but", "or", "nor",
    "for", "so", "yet", "in", "on", "at", "by", "from", "to", "with",
    "about", "above", "after", "again", "against", "all", "am", "as",
    "because", "before", "below", "between", "both", "during", "each",
    "few", "further", "here", "how", "i", "if", "into", "it", "its", "itself",
    "just", "me", "more", "most", "my", "myself", "no", "not", "now", "of",
    "off", "once", "only", "other", "our", "ours", "ourselves", "out", "over",
    "own", "same", "she", "he", "they", "them", "their", "theirs", "themselves",
    "then", "there", "these", "this", "those", "through", "too", "under",
    "until", "up", "very", "we", "what", "when", "where", "which", "while",
    "who", "whom", "why", "you", "your", "yours", "yourself", "yourselves"
])

def _extract_arxiv_id(id_or_url: str) -> str | None:
    """
    Extracts arXiv ID from a string (ID or URL).
    Handles formats like: 1234.5678, 2303.10130v1, hep-th/0101001
    """
    # Regex to find arXiv ID patterns (e.g., 1234.5678, 2303.10130v1, hep-th/0101001)
    # Updated regex to be more robust for various ID formats including older ones
    match = re.search(r"(\d{4}\.\d{4,5}(v\d+)?|[a-zA-Z.-]+/\d{7}(v\d+)?)", id_or_url)
    if match:
        # Further check if it's part of a URL and extract the core ID
        core_id_match = re.search(r"([a-zA-Z.-]*\d{4}\.\d{4,5}(v\d)?|[a-zA-Z.-]+/\d{7}(v\d)?)", match.group(0))
        if core_id_match:
            return core_id_match.group(0)
        return match.group(0) # Fallback to the broader match if specific sub-match fails
    return None

def search_arxiv_papers(query: str) -> dict:
    """
    Searches arXiv for papers matching the query.

    Args:
        query: The search query string.

    Returns:
        A dictionary containing the search results or an error message.
    """
    try:
        search = arxiv.Search(
            query=query,
            max_results=5,  # Limit to 5 results
            sort_by=arxiv.SortCriterion.Relevance
        )

        papers_list = []
        for result in search.results():
            paper_details = {
                "title": result.title,
                "authors": [author.name for author in result.authors],
                "published_date": result.published.strftime('%Y-%m-%d'),
                "summary": result.summary,
                "arxiv_id": result.entry_id.split('/')[-1],  # Extract ID like '2303.10130'
                "primary_category": result.primary_category,
                "pdf_link": result.pdf_url
            }
            papers_list.append(paper_details)

        if not papers_list:
            return {"status": "success", "papers": [], "message": "No papers found matching your query."}

        return {"status": "success", "papers": papers_list}

    except Exception as e:
        return {"status": "error", "message": str(e)}

def summarize_arxiv_paper(arxiv_id_or_url: str) -> dict:
    """
    Fetches and summarizes a specific arXiv paper by its ID or URL.

    Args:
        arxiv_id_or_url: The arXiv ID (e.g., "2303.10130") or URL 
                         (e.g., "https://arxiv.org/abs/2303.10130").

    Returns:
        A dictionary containing the paper's details or an error message.
    """
    try:
        arxiv_id = _extract_arxiv_id(arxiv_id_or_url)
        if not arxiv_id:
            return {"status": "error", "message": "Invalid arXiv ID or URL format."}

        search = arxiv.Search(id_list=[arxiv_id])
        paper = next(search.results(), None)

        if paper:
            paper_details = {
                "title": paper.title,
                "authors": [author.name for author in paper.authors],
                "published_date": paper.published.strftime('%Y-%m-%d'),
                "summary": paper.summary,  # This is the abstract
                "arxiv_id": paper.entry_id.split('/')[-1],
                "primary_category": paper.primary_category,
                "pdf_link": paper.pdf_url
            }
            return {"status": "success", "paper": paper_details}
        else:
            return {"status": "error", "message": "Paper not found or invalid ID."}

    except Exception as e:
        return {"status": "error", "message": str(e)}

def answer_paper_question(arxiv_id_or_url: str, question: str) -> dict:
    """
    Answers a question about an arXiv paper based on its abstract.

    Args:
        arxiv_id_or_url: The arXiv ID or URL of the paper.
        question: The question to answer.

    Returns:
        A dictionary with the answer or an error message.
    """
    try:
        arxiv_id = _extract_arxiv_id(arxiv_id_or_url)
        if not arxiv_id:
            return {"status": "error", "message": "Invalid arXiv ID or URL format."}

        search = arxiv.Search(id_list=[arxiv_id])
        paper = next(search.results(), None)

        if not paper:
            return {"status": "error", "message": f"Paper with ID '{arxiv_id}' not found."}

        abstract = paper.summary
        title = paper.title

        # Tokenize question and remove stop words
        question_words = [word for word in re.split(r'\W+', question.lower()) if word and word not in STOP_WORDS]

        if not question_words:
            return {
                "status": "success",
                "answer_type": "not_enough_keywords",
                "message": "Your question did not contain enough significant keywords after removing common words. Please try a more specific question.",
                "abstract": abstract,
                "title": title
            }

        # Basic keyword matching in abstract
        found_keywords = 0
        abstract_lower = abstract.lower()
        for word in question_words:
            if word in abstract_lower:
                found_keywords += 1
        
        # Consider it a match if more than half of the significant keywords are found
        # This threshold can be adjusted.
        if found_keywords > len(question_words) / 2:
            return {
                "status": "success",
                "answer_type": "found_in_abstract",
                "message": "The abstract may contain information relevant to your question. Please review it.",
                "abstract": abstract,
                "title": title
            }
        else:
            return {
                "status": "success",
                "answer_type": "not_found_in_abstract",
                "message": "I could not find specific information for your question in the paper's abstract.",
                "abstract": abstract,
                "title": title
            }

    except Exception as e:
        # Log the exception e for debugging in a real application
        return {"status": "error", "message": f"An error occurred: {str(e)}"}


if __name__ == '__main__':
    # Example Usage for search_arxiv_papers (optional, for testing)
    print("--- Testing search_arxiv_papers ---")
    test_query = "quantum computing"
    search_results = search_arxiv_papers(test_query)

    if search_results["status"] == "success":
        print(f"Found {len(search_results['papers'])} papers for '{test_query}':")
        for paper in search_results['papers']:
            print(f"  Title: {paper['title']}")
            print(f"  Authors: {', '.join(paper['authors'])}")
            print(f"  Published: {paper['published_date']}")
            print(f"  ID: {paper['arxiv_id']}")
            print(f"  Category: {paper['primary_category']}")
            print(f"  PDF: {paper['pdf_link']}")
            print(f"  Summary: {paper['summary'][:200]}...") # Print first 200 chars of summary
            print("-" * 20)
    elif search_results["status"] == "error":
        print(f"Error searching arXiv: {search_results['message']}")
    
    test_query_no_results = "nonexistenttopicxyz123"
    search_results_no_results = search_arxiv_papers(test_query_no_results)
    if search_results_no_results["status"] == "success" and not search_results_no_results["papers"]:
        print(f"\nTest for no results: {search_results_no_results['message']}")
    elif search_results_no_results["status"] == "error":
        print(f"\nError during no results test: {search_results_no_results['message']}")

    # Test with a query that might cause an error (e.g., too broad, though arxiv library might handle this gracefully)
    # Forcing an error is hard without knowing internal library vulnerabilities or network issues.
    # This part is more conceptual for now.
    # For example, if arxiv.Search itself could fail for specific query patterns (unlikely for simple strings)
    # or if there was a network issue, the except block should catch it.
    print("\nNote: True error condition (e.g., network failure) is hard to simulate reliably in this script for search.")

    # Example Usage for summarize_arxiv_paper (optional, for testing)
    print("\n--- Testing summarize_arxiv_paper ---")
    
    # Test with a valid arXiv ID
    valid_id = "2303.10130"  # Replace with a known valid ID if needed
    summary_result_id = summarize_arxiv_paper(valid_id)
    if summary_result_id["status"] == "success":
        paper = summary_result_id["paper"]
        print(f"\nSummary for ID '{valid_id}':")
        print(f"  Title: {paper['title']}")
        print(f"  Authors: {', '.join(paper['authors'])}")
        print(f"  Published: {paper['published_date']}")
        print(f"  Summary: {paper['summary'][:200]}...")
    elif summary_result_id["status"] == "error":
        print(f"\nError summarizing ID '{valid_id}': {summary_result_id['message']}")

    # Test with a valid arXiv URL
    valid_url = "https://arxiv.org/abs/2303.10130" # Replace with a known valid URL
    summary_result_url = summarize_arxiv_paper(valid_url)
    if summary_result_url["status"] == "success":
        paper = summary_result_url["paper"]
        print(f"\nSummary for URL '{valid_url}':")
        print(f"  Title: {paper['title']}")
        # print(f"  Summary: {paper['summary'][:200]}...") # Already printed above if same paper
    elif summary_result_url["status"] == "error":
        print(f"\nError summarizing URL '{valid_url}': {summary_result_url['message']}")

    # Test with an invalid/non-existent arXiv ID
    invalid_id = "0000.00000"
    summary_result_invalid = summarize_arxiv_paper(invalid_id)
    if summary_result_invalid["status"] == "error":
        print(f"\nTest for invalid ID '{invalid_id}': {summary_result_invalid['message']}")
    else:
        print(f"\nTest for invalid ID '{invalid_id}' failed: {summary_result_invalid}")
        
    # Test with a badly formatted ID (should also lead to error)
    bad_format_id = "this-is-not-an-id"
    summary_result_bad_format = summarize_arxiv_paper(bad_format_id)
    if summary_result_bad_format["status"] == "error":
        print(f"\nTest for badly formatted ID '{bad_format_id}': {summary_result_bad_format['message']}")
    else:
        print(f"\nTest for badly formatted ID '{bad_format_id}' failed: {summary_result_bad_format}")
    
    # Example Usage for answer_paper_question (optional, for testing)
    print("\n--- Testing answer_paper_question ---")
    paper_id_for_qna = "2303.10130" # Use a known paper
    
    # Test case 1: Question with keywords likely in abstract
    question1 = "What are the key results of this paper regarding large language models?"
    answer1 = answer_paper_question(paper_id_for_qna, question1)
    print(f"\nQuestion 1: '{question1}'")
    print(f"Answer 1: {answer1['status']} - {answer1['message']}")
    if answer1['status'] == 'success' and 'abstract' in answer1:
        print(f"Abstract sample: {answer1['abstract'][:100]}...")

    # Test case 2: Question with keywords unlikely in abstract
    question2 = "Does this paper discuss recipes for apple pie?"
    answer2 = answer_paper_question(paper_id_for_qna, question2)
    print(f"\nQuestion 2: '{question2}'")
    print(f"Answer 2: {answer2['status']} - {answer2['message']}")

    # Test case 3: Question with only stop words
    question3 = "is it the an"
    answer3 = answer_paper_question(paper_id_for_qna, question3)
    print(f"\nQuestion 3: '{question3}'")
    print(f"Answer 3: {answer3['status']} - {answer3['message']}")

    # Test case 4: Invalid paper ID
    question4 = "What about this paper?"
    invalid_paper_id_for_qna = "0000.0000_invalid"
    answer4 = answer_paper_question(invalid_paper_id_for_qna, question4)
    print(f"\nQuestion 4: '{question4}' for ID '{invalid_paper_id_for_qna}'")
    print(f"Answer 4: {answer4['status']} - {answer4['message']}")

    # Test case 5: Using a URL
    paper_url_for_qna = "https://arxiv.org/abs/2303.10130"
    question5 = "What is the methodology used?"
    answer5 = answer_paper_question(paper_url_for_qna, question5)
    print(f"\nQuestion 5: '{question5}' for URL '{paper_url_for_qna}'")
    print(f"Answer 5: {answer5['status']} - {answer5['message']}")

    # Test _extract_arxiv_id
    print("\n--- Testing _extract_arxiv_id ---")
    ids_to_test = [
        "2303.10130", "https://arxiv.org/abs/2303.10130", "arxiv.org/pdf/2303.10130v1.pdf",
        "1234.56789", "cond-mat/0123456", "https://arxiv.org/abs/cond-mat/0123456v2",
        "This is my paper 2401.00001, check it out!", "No ID here", "http://example.com/1234.5678"
    ]
    expected_ids = [
        "2303.10130", "2303.10130", "2303.10130v1", 
        "1234.56789", "cond-mat/0123456", "cond-mat/0123456v2",
        "2401.00001", None, "1234.5678" # Assuming the regex is greedy for the last one
    ]

    for i, id_str in enumerate(ids_to_test):
        extracted = _extract_arxiv_id(id_str)
        print(f"Input: \"{id_str}\" -> Extracted: \"{extracted}\", Expected: \"{expected_ids[i]}\" {'PASS' if extracted == expected_ids[i] else 'FAIL'}")

    # A more specific test for the regex in _extract_arxiv_id for older formats
    old_id_test = "https://arxiv.org/abs/hep-th/0101001"
    extracted_old_id = _extract_arxiv_id(old_id_test)
    print(f"Input: \"{old_id_test}\" -> Extracted: \"{extracted_old_id}\", Expected: \"hep-th/0101001\" {'PASS' if extracted_old_id == 'hep-th/0101001' else 'FAIL'}")
    
    another_id = "cs.CV/0102003"
    extracted_another_id = _extract_arxiv_id(another_id)
    print(f"Input: \"{another_id}\" -> Extracted: \"{extracted_another_id}\", Expected: \"cs.CV/0102003\" {'PASS' if extracted_another_id == 'cs.CV/0102003' else 'FAIL'}")

    id_with_version = "1706.03762v5"
    extracted_id_with_version = _extract_arxiv_id(id_with_version)
    print(f"Input: \"{id_with_version}\" -> Extracted: \"{extracted_id_with_version}\", Expected: \"1706.03762v5\" {'PASS' if extracted_id_with_version == '1706.03762v5' else 'FAIL'}")
