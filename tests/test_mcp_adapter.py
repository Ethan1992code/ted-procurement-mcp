from ted_procurement_mcp.mcp_adapter import register_tools


class FakeServer:
    def __init__(self):
        self.names = []
        self.functions = {}

    def tool(self, **kwargs):
        def decorator(fn):
            name = kwargs.get("name") or fn.__name__
            self.names.append(name)
            self.functions[name] = fn
            return fn
        return decorator


class DummyService:
    pass


def test_register_tools_exposes_expected_v2_tools():
    server = FakeServer()
    register_tools(server, DummyService())
    assert server.names == [
        "raw_ted_search",
        "search_procurements",
        "find_opportunities",
        "get_notice",
        "find_buyers",
        "buyer_history",
        "find_awards",
        "market_stats",
        "suggest_cpv",
        "upsert_supplier_profile",
        "get_supplier_profile",
        "match_supplier_opportunities",
        "sync_notices",
        "daily_opportunities",
        "warehouse_stats",
    ]
