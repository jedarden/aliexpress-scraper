import scraper

AliExpress = scraper.AliExpress()

while True:
    AliExpress.ParseCategoryProducts(10)