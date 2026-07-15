import pandas as pd

from app import universe


def test_filter_listed_equities_excludes_non_common_security_types():
    table = pd.DataFrame(
        {
            "Symbol": ["AAPL", "DAVEW", "NAMMW", "SPACU", "ACMER", "PREFP", "NOTEZ"],
            "Security Name": [
                "Apple Inc. Common Stock",
                "Dave Inc. Warrants",
                "Namma Corp. Warrant",
                "Example Acquisition Units",
                "Acme Corporation Rights",
                "Example Preferred Stock",
                "Example 5.00% Notes due 2030",
            ],
            "Test Issue": ["N"] * 7,
            "ETF": ["N"] * 7,
            "NextShares": ["N"] * 7,
            "Financial Status": ["N"] * 7,
            "Market Category": ["Q"] * 7,
        }
    )

    assert universe._filter_listed_equities(table, "Symbol") == ["AAPL"]


def test_common_stock_ending_in_w_is_not_removed_by_symbol_suffix():
    table = pd.DataFrame(
        {
            "Symbol": ["ABCDW"],
            "Security Name": ["ABCDW Holdings Common Stock"],
            "Test Issue": ["N"],
            "ETF": ["N"],
            "NextShares": ["N"],
            "Financial Status": ["N"],
            "Market Category": ["Q"],
        }
    )

    assert universe._filter_listed_equities(table, "Symbol") == ["ABCDW"]
