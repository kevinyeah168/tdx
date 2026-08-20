from workbench.providers.base import QuoteProvider


class BadQuoteProvider:
    def quotes(self, symbols: list[int]) -> int:
        return len(symbols)


quote_provider: QuoteProvider = BadQuoteProvider()
