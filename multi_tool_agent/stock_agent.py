from datetime import datetime, timedelta
import yfinance as yf


def calculate_performance(symbol: str, days_ago: int):
    """
    Calculates the percentage change in stock price over a period.
    Internal helper or can be exposed as a tool.
    Returns performance percentage or None if calculation fails.
    """
    try:
        ticker = yf.Ticker(symbol)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_ago)

        historical_data = ticker.history(
            start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d")
        )

        if historical_data.empty or len(historical_data["Close"]) < 1:
            print(
                f"No historical data for {symbol} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
            )
            # If only one data point is available (e.g. days_ago=0 or period is very short)
            # we might not be able to calculate change in the same way.
            # For days_ago > 0, we expect at least two points for a change.
            # If len is 1, it means data for start_date and end_date might be the same day or only one point was fetched.
            # Let's refine this: we need data for the start of the period and the end.
            # If days_ago is 0, this function might not be meaningful for "change".
            # For simplicity, if not enough data points for a clear start/end, return None.
            if (
                len(historical_data["Close"]) < 2 and days_ago > 0
            ):  # Need two points for old and new price if period > 0
                print(
                    f"Not enough distinct data points for {symbol} to calculate performance over {days_ago} days."
                )
                return None
            elif historical_data.empty:
                return None

        # If days_ago = 0, old_price and new_price would be the same if only one data point.
        # If multiple data points for the same day (intraday), iloc[0] and iloc[-1] could differ.
        # yfinance daily history usually gives one point per day.
        old_price = historical_data["Close"].iloc[0]
        new_price = historical_data["Close"].iloc[-1]

        if old_price == 0:  # Avoid division by zero
            return 0.0
        percent_change = ((new_price - old_price) / old_price) * 100
        return round(percent_change, 2)
    except Exception as e:
        print(f"Error in calculate_performance for {symbol} over {days_ago} days: {e}")
        return None


def get_best_performing(stocks: list[str], days_ago: int) -> dict:
    """
    Finds the best performing stock from a list over a specified number of days.
    Args:
        stocks (list[str]): A list of stock symbols (e.g., ["AAPL", "MSFT"]).
        days_ago (int): The number of days to look back for performance calculation. Must be positive.
    Returns:
        dict: Contains the best_stock and best_performance, or an error message.
    """
    best_stock_symbol = None
    max_performance = -float("inf")

    if not stocks:
        return {"status": "error", "message": "Stock list cannot be empty."}
    if not isinstance(days_ago, int) or days_ago <= 0:
        return {"status": "error", "message": "Days ago must be a positive integer."}

    for symbol in stocks:
        performance = calculate_performance(symbol, days_ago)
        if performance is not None:
            if performance > max_performance:
                max_performance = performance
                best_stock_symbol = symbol
        else:
            print(
                f"Could not calculate performance for {symbol} in get_best_performing for period {days_ago} days."
            )

    if best_stock_symbol:
        return {
            "status": "success",
            "best_stock": best_stock_symbol,
            "performance_percent": max_performance,
            "period_days": days_ago,
        }
    else:
        return {
            "status": "error",
            "message": f"Could not determine the best performing stock from the list: {stocks} over {days_ago} days. Ensure symbols are valid and data is available for the period.",
        }


def get_stock_price(symbol: str) -> dict:
    """
    Gets the current or most recent closing price of a stock.
    Args:
        symbol (str): The stock symbol (e.g., "AAPL").
    Returns:
        dict: Contains the stock symbol and its price, or an error message.
    """
    try:
        ticker = yf.Ticker(symbol)
        # Using history(period='1d') might give yesterday's close if market is closed.
        # For a more "current" price, ticker.info['currentPrice'] or similar can be used,
        # but it's not always available for all symbols or exchanges.
        # Let's try a robust approach:
        info = ticker.info
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")

        if current_price:
            return {
                "status": "success",
                "symbol": symbol,
                "price": round(current_price, 2),
            }

        # Fallback to recent history if specific current price fields are not available
        todays_data = ticker.history(
            period="2d"
        )  # Fetch 2 days to ensure we get the latest close
        if not todays_data.empty:
            return {
                "status": "success",
                "symbol": symbol,
                "price": round(todays_data["Close"].iloc[-1], 2),
            }

        # Further fallback if even history is problematic
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        if prev_close:
            return {
                "status": "success",
                "symbol": symbol,
                "price": round(prev_close, 2),
            }

        return {
            "status": "error",
            "message": f"Could not retrieve current price for {symbol}. Data might be unavailable.",
        }

    except Exception as e:
        print(f"Error in get_stock_price for {symbol}: {e}")
        # Check if the error is due to an invalid symbol (common with yfinance)
        if "No data found for symbol" in str(e) or "No timezone found" in str(
            e
        ):  # Common yfinance errors for bad symbols
            return {
                "status": "error",
                "message": f"Invalid symbol or no data found for {symbol}.",
            }
        return {
            "status": "error",
            "message": f"Could not retrieve price for {symbol}: An unexpected error occurred.",
        }


def get_price_change_percent(symbol: str, days_ago: int) -> dict:
    """
    Calculates the percentage change in a stock's price over a specified number of days.
    Args:
        symbol (str): The stock symbol (e.g., "AAPL").
        days_ago (int): The number of days to look back for the price change calculation. Must be positive.
    Returns:
        dict: Contains the symbol, percentage change, and period, or an error message.
    """
    if not isinstance(days_ago, int) or days_ago <= 0:
        return {"status": "error", "message": "Days ago must be a positive integer."}

    performance = calculate_performance(symbol, days_ago)
    if performance is not None:
        return {
            "status": "success",
            "symbol": symbol,
            "price_change_percent": performance,
            "period_days": days_ago,
        }
    else:
        return {
            "status": "error",
            "message": f"Could not calculate price change for {symbol} over {days_ago} days. Ensure symbol is valid and data is available for the period.",
        }
