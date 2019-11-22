import scraper, traceback

try:
    AliExpress = scraper.AliExpress()

    AliExpress.ScrapeCategories()
except:
    traceback.print_exc()