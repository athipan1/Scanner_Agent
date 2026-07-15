from app.data_sources import financial_statements


class Frame:
    def __init__(self, empty):
        self.empty = empty


def test_first_non_empty_lazy_stops_after_first_success():
    calls = []

    def empty_loader():
        calls.append("empty")
        return Frame(empty=True)

    def success_loader():
        calls.append("success")
        return Frame(empty=False)

    def must_not_run():
        calls.append("unexpected")
        raise AssertionError("fallback executed after success")

    result = financial_statements._first_non_empty_lazy(
        empty_loader,
        success_loader,
        must_not_run,
    )

    assert result.empty is False
    assert calls == ["empty", "success"]


def test_first_non_empty_lazy_continues_after_provider_exception():
    calls = []

    def failed_loader():
        calls.append("failed")
        raise RuntimeError("provider unavailable")

    def success_loader():
        calls.append("success")
        return Frame(empty=False)

    result = financial_statements._first_non_empty_lazy(
        failed_loader,
        success_loader,
    )

    assert result.empty is False
    assert calls == ["failed", "success"]
