import requests, random, math, base64, json, time, html, traceback, dateutil.parser, hashlib
from sqlalchemy import create_engine
from sqlalchemy.sql import text

class AliExpress():
    def __init__(self):
        self.DBServer = "servename"
        self.DBUser = "username"
        self.DBPassword = "password"
        self.DBDatabase = "database_name"

        self.db_string = f'''postgres://{self.DBUser}:{self.DBPassword}@{self.DBServer}/{self.DBDatabase}'''

        #Connect to the database. 
        self.db = create_engine(self.db_string)

    def ScrapeCategories(self):
        pass
        #Load the homepage. 
        URL = 'https://www.aliexpress.com'
        HTML = self.get_url_contents(URL)

        CategoryDict = self.ParseCategories(HTML)

        self.LoadCategories(CategoryDict)

    def LoadCategories(self, CategoryDict):
        '''
        CategoryDict should be a dictionary of dictionaries. Key is the ID of the category. Value is the dict structure below. 

        One Category Dict has the the following attributes: 
        CategoryID[int]
        URL[str]
        CategoryName[str]
        '''

        InsertList = list(CategoryDict.values())
        LastDiscoveredTime = int(time.time())
        TotalRows = 0

        for OneCategory in InsertList:
            OneCategory['LastDiscovered'] = LastDiscoveredTime

            SQL = text('''INSERT INTO "CategoryURLs" ("CategoryID", "URL", "CategoryName", "LastDiscovered") VALUES (:CategoryID, :URL, :CategoryName, :LastDiscovered) ON CONFLICT ("CategoryID") DO UPDATE SET "LastDiscovered" = EXCLUDED."LastDiscovered"''')

            Response = self.db.execute(SQL, OneCategory)
            TotalRows += Response.rowcount
            
        return TotalRows

    def LoadProducts(self, ProductList):
        '''
        ProductList should be a list of dictionaries.

        One Element has the following attributes

        ProductID[int]
        VendorID[int]
        Orders[int]
        Rating[float]
        Name[str]
        URL[str]
        LastDiscovered[int]
        '''

        LastDiscoveredTime = int(time.time())
        TotalRows = 0
        
        for OneProduct in ProductList:
            OneProduct['LastDiscovered'] = LastDiscoveredTime

            SQL = text('''INSERT INTO "ProductSnapshot" ("ProductID", "VendorID", "Orders", "Rating", "Name", "URL", "LastDiscovered") VALUES (:ProductID, :VendorID, :Orders, :Rating, :Name, :URL, :LastDiscovered) ON CONFLICT ("ProductID") DO UPDATE SET "VendorID" = EXCLUDED."VendorID", "Orders" = EXCLUDED."Orders", "Rating" = EXCLUDED."Rating", "Name" = EXCLUDED."Name", "URL" = EXCLUDED."URL", "LastDiscovered" = EXCLUDED."LastDiscovered"''')

            Response = self.db.execute(SQL, OneProduct)
            TotalRows += Response.rowcount
        return TotalRows

    def LoadOrders(self, OrderList, ProductInfo):
        '''
        OrderList should be a list of dictionaries

        One Element has the following attributes. 

        TransactionID[int]
        ProductID[int]
        Name[str]
        CountryCode[str]
        CountryName[str]
        BuyerAcccountPointLevel[str]
        Quantity[int]
        Unit[str]
        LotNum[int]
        Date[int]
        Hour[int]
        '''
        TotalRows = 0
        MaxOrderTime = ProductInfo['LastTransactionTime']
        for OneOrder in OrderList:
        
            OneOrder['ProductID'] = ProductInfo['ProductID']
            OneOrder['unixdate'] = int(dateutil.parser.parse(OneOrder['date']).timestamp())
            OneOrder['hour'] = OneOrder['unixdate'] - (OneOrder['unixdate'] % 3600)
            OneOrder['CaptureTime'] = time.time()
            OneOrder['TransactionID'] = f'''|{OneOrder['CaptureTime']}{OneOrder['ProductID']}{OneOrder['name']}{OneOrder['countryCode']}{OneOrder['buyerAccountPointLeval']}{OneOrder['quantity']}{OneOrder['unixdate']}'''.zfill(64)

            SQL = text('''INSERT INTO "ProductOrderDetails" ("TransactionID", "ProductID", "Name", "CountryCode", "BuyerAccountPointLevel", "Quantity", "Unit", "LotNum", "Date", "Hour", "CaptureTime") VALUES (:TransactionID, :ProductID, :name, :countryCode, :buyerAccountPointLeval, :quantity, :unit, :lotNum, :unixdate, :hour, :CaptureTime) ON CONFLICT ("TransactionID") DO NOTHING''')
            Response = self.db.execute(SQL, OneOrder)
            TotalRows += Response.rowcount

            MaxOrdertime = max(MaxOrderTime, ProductInfo['LastTransactionTime'])

        #Update the product snapshot with the latest order.     
        Parameters = {}
        Parameters['LastTransactionTime'] = MaxOrderTime
        Parameters['ProductID'] = ProductInfo['ProductID']

        SQL = text('''UPDATE "ProductSnapshot" SET "LastTransactionTime" = :LastTransactionTime WHERE "ProductID" = :ProductID''')
        self.db.execute(SQL, Parameters)

        return TotalRows

    def ParseCategories(self, HTML):
        #Look for category URLs
        SeekString = 'aliexpress.com/category/'

        Categories = {}

        while HTML.find(SeekString) > -1:
            OneCategory = {}
            
            OneCategory['Info'] = self.fetchBetween('aliexpress.com/categor', 'a>', HTML)
            OneCategory['Page'] = self.fetchBetween('y/', '.html', OneCategory['Info'])
            OneCategory['URL'] ='https://www.aliexpress.com/category/'+str(OneCategory['Page'])+'.html'
            OneCategory['CategoryID'] = self.fetchBetween('y/', '/', OneCategory['Info'])
            OneCategory['CategoryName'] = self.fetchBetween('">', '</', OneCategory['Info'])
            
            if OneCategory['CategoryID'].isdigit():
                Categories[OneCategory['CategoryID']] = OneCategory
            HTML = HTML[HTML.find(SeekString) + len(SeekString):]

        return Categories

    def ParseCategoryProducts(self, NumCategories = 10):
        #Using one category, get a list of products with at least 1000 orders listed. 
        Parameters = {}
        Parameters['NumCategories'] = NumCategories
        Parameters['Threshold'] = int(time.time()) - 86400 #24 hrs in the past

        SQL = text('''SELECT "CategoryID", "URL", "CategoryName" FROM "CategoryURLs" WHERE "LastChecked" < :Threshold LIMIT :NumCategories OFFSET 0''')

        #Get list of categories. 
        Categories = self.db.execute(SQL, Parameters).fetchall()

        while len(Categories) < NumCategories:
            Parameters['Threshold'] += 3600

            Categories.extend(self.db.execute(SQL, Parameters).fetchall())

        #Scrape all the relevant products for each category. 
        for OneCategory in Categories:
            print("Pulling Products for", OneCategory['CategoryName'])
            ProductList = self.ParseOneCategory(OneCategory)

            #Insert the product list into the database. This will allow for a pause between http requests.
            TotalRows = self.LoadProducts(ProductList)

            print(TotalRows, "Products Added for", OneCategory['CategoryName'])

            #Update the LastChecked value in the category. 
            Parameters = {}
            Parameters['LastChecked'] = int(time.time())
            Parameters['CategoryID'] = OneCategory['CategoryID']

            SQL = text('''UPDATE "CategoryURLs" SET "LastChecked" = :LastChecked WHERE "CategoryID" = :CategoryID''')
            Output = self.db.execute(SQL, Parameters)

    def ScrapeOrders(self, NumProducts=10):
        #For each product, persist the orders that haven't already been persisted.
        Parameters = {}
        Parameters['NumProducts'] = NumProducts
        Parameters['CurrentTime'] = int(time.time())
        SQL = text('''SELECT "ProductID", "Name" FROM "ProductSnapshot" WHERE "Orders" > 1000 AND "NextOrderCheck" < :CurrentTime LIMIT :NumProducts OFFSET 0''')

        #Get list of products
        Products = self.db.execute(SQL, Parameters).fetchall()

        while len(Products) < NumProducts:
            Parameters['CurrentTime'] += 3600
            Parameters['NumProducts'] = NumProducts - len(Products)

            Products.extend(self.db.execute(SQL, Parameters).fetchall())

        #Scrape all the transactions which have not already been captured. 
        for OneProduct in Products:
            
            NumRows = self.GetProductBuyers(OneProduct['ProductID'])

            print(NumRows, "Pulling", OneProduct['Name'])

    def GetProductBuyers(self, ProductID, Lookback=86400):

        #Calculate the cutoff time. Default is 24 hrs in the past. 
        CutoffTime = int(time.time()) - Lookback
        
        Page = 1
        MinimumTransaction = int(time.time())
        NumOrders = 0
        LargestBuyer = 0
        LargestBuyerItems = 0

        BuyerDict = {}

        while MinimumTransaction > CutoffTime and Page <= 50:
            #Keep pulling pages until the cutoff time is hit, or 50 pages is hit. 
            Result = self.GetOneOrder(ProductID, Page)

            for OneTransaction in Result['records']:

                TransactionTime = int(dateutil.parser.parse(OneTransaction['date']).timestamp())

                MinimumTransaction = min(TransactionTime, MinimumTransaction)

                if MinimumTransaction < CutoffTime:
                    break

                BuyerName = OneTransaction['name']+"|"+OneTransaction['countryCode']+"|"+OneTransaction['buyerAccountPointLeval']+"|"+OneTransaction['unit']

                if BuyerName not in BuyerDict.keys():
                    BuyerDict[BuyerName] = {}
                    BuyerDict[BuyerName]['NumOrders'] = 0
                    BuyerDict[BuyerName]['NumItems'] = 0
                BuyerDict[BuyerName]['NumOrders'] += 1
                BuyerDict[BuyerName]['NumItems'] += int(OneTransaction['quantity'])
                if BuyerDict[BuyerName]['NumOrders'] > LargestBuyer:
                    LargestBuyer = BuyerDict[BuyerName]['NumOrders']
                    LargestBuyerItems = BuyerDict[BuyerName]['NumItems']
                NumOrders += 1
            

            Page += 1
        
        Parameters = {}
        if NumOrders > 0:
            Parameters['ProductID'] = ProductID
            Parameters['LastOrderCheck'] = int(time.time())
            Parameters['NextOrderCheck'] = int(time.time()) + min(86400, (int(time.time()) - MinimumTransaction) / NumOrders * 100)
            Parameters['NumBuyers'] = len(BuyerDict.keys())
            Parameters['NumOrders'] = NumOrders
            Parameters['LargestBuyer'] = LargestBuyer
            Parameters['LargestBuyerItems'] = LargestBuyerItems
            Parameters['NumPages'] = Page
        else:
            Parameters['ProductID'] = ProductID
            Parameters['LastOrderCheck'] = int(time.time())
            Parameters['NextOrderCheck'] = int(time.time()) + 86400
            Parameters['NumBuyers'] = 0
            Parameters['NumOrders'] = 0
            Parameters['LargestBuyer'] = 0
            Parameters['LargestBuyerItems'] = 0
            Parameters['NumPages'] = 1
        SQL = text('''UPDATE "ProductSnapshot" SET "LastOrderCheck" = :LastOrderCheck, "NextOrderCheck" = :NextOrderCheck, "NumBuyers" = :NumBuyers, "NumOrders" = :NumOrders, "LargestBuyer" = :LargestBuyer, "LargestBuyerItems" = :LargestBuyerItems, "NumPages" = :NumPages WHERE "ProductID" = :ProductID''')

        self.db.execute(SQL, Parameters)
        return Parameters

    def GetOneOrder(self, ProductID, Page):
        URL = f'''https://feedback.aliexpress.com/display/evaluationProductDetailAjaxService.htm?productId={ProductID}&type=default&page={Page}'''
        PageData = json.loads(self.get_url_contents(URL))

        return PageData
    
    def ParseOneCategory(self, OneCategoryInput, Page =1, OrderMinimum = 1000):
        print(OneCategoryInput['CategoryName'], "Page:", Page)

        #Keep iterating through until a product is found which is less than the OrderMinimum. 
        URL = f'''https://www.aliexpress.com/glosearch/api/product?ltype=wholesale&CatId={OneCategoryInput['CategoryID']}&categoryBrowse=y&SortType=total_tranpro_desc&g=n&isrefine=y&switch_new_app=y&page={Page}'''

        print(URL)
        
        try:
            result = html.unescape(self.get_url_contents(URL))
            PageData = json.loads(result)
        except:
            print(result)
            pass
        
        #Get all the categories. 
        Categories = {}
        if 'refineCategory' in PageData.keys():
            for OneCategory in PageData['refineCategory']:
                #Parse the parent. 
                OneCategoryOutput = {}

                OneCategoryOutput['CategoryID'] = OneCategory['categoryId']
                OneCategoryOutput['URL'] = f'''https:{OneCategory['categoryUrl']}'''
                OneCategoryOutput['CategoryName'] = OneCategory['categoryEnName']
                Categories[OneCategoryOutput['CategoryID']] = OneCategoryOutput

                if 'childCategories' in OneCategory.keys():
                    for OneChildCategory in OneCategory['childCategories']:
                        OneCategoryOutput = {}

                        OneCategoryOutput['CategoryID'] = OneChildCategory['categoryId']
                        OneCategoryOutput['URL'] = f'''https:{OneChildCategory['categoryUrl']}'''
                        OneCategoryOutput['CategoryName'] = OneChildCategory['categoryEnName']
                        Categories[OneCategoryOutput['CategoryID']] = OneCategoryOutput

        #Load the categories into the database. 
        self.LoadCategories(Categories)

        #Parse all the products. 
        ProductList = []
        MinimumOrder = -1

        #No Products being sold in this category
        if 'items' not in PageData.keys():
            return ProductList

        for OneItem in PageData['items']:
            try:
                OneProduct = {}
                OneProduct['ProductID'] = OneItem['productId']
                if 'store' in OneItem.keys():
                    OneProduct['VendorID'] = OneItem['store']['storeId']
                else:
                    OneProduct['VendorID'] = -1
                if 'tradeDesc' in OneItem.keys():
                    OneProduct['Orders'] = OneItem['tradeDesc'].replace(' Sold', '')
                else:
                    OneProduct['Orders'] = 0
                if 'starRating' in OneItem.keys():
                    OneProduct['Rating'] = float(OneItem['starRating'])
                else:
                    OneProduct['Rating'] = 0.0
                OneProduct['Name'] = OneItem['title']
                OneProduct['URL'] = f'''https:{OneItem['productDetailUrl']}'''
                if str(OneProduct['Orders']).isdigit():
                    OneProduct['Orders'] = int(OneProduct['Orders'])
                    ProductList.append(OneProduct)

                    if MinimumOrder == -1 or MinimumOrder > OneProduct['Orders']:
                        MinimumOrder = OneProduct['Orders']
            except Exception as e:
                traceback.print_exc()
                print(json.dumps(OneItem, indent=4))
                pass
        if MinimumOrder == -1:
            #No orders were added to the list. 
            return ProductList
        if MinimumOrder >= OrderMinimum: 
            #There are still orders to add to the list.
            Page += 1
            NextPage = self.ParseOneCategory(OneCategoryInput, Page, OrderMinimum = OrderMinimum)
            if len(NextPage) > 0:
                ProductList.extend(NextPage)
            return ProductList
        else:
            #All eligible orders have been added to the list.
            print("MinimumOrder:", MinimumOrder)
            return ProductList

    def fetchBetween(self, needle1, needle2, haystack, include=False):
        position1 = haystack.find(needle1)
        
        if position1 == -1:
            return ''
        
        if include == False:
            position1 += len(needle1)
            
        position2 = haystack.find(needle2, position1)	
        
        if position2 == -1:
            return ''
        
        if include == True:
            position2 += len(needle2)
        
        length = position2 - position1
        
        substring = haystack[position1:(position1 + length)]
        
        return substring.strip()	
    
    def RandomUserAgents(self):
        UA = []
        UA.append('Mozilla/5.0 (Windows NT 5.1; rv:7.0.1) Gecko/20100101 Firefox/7.0.1')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:54.0) Gecko/20100101 Firefox/54.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:18.0) Gecko/20100101 Firefox/18.0')
        UA.append('Mozilla/5.0 (Windows NT 5.1; rv:36.0) Gecko/20100101 Firefox/36.0')
        UA.append('Mozilla/5.0 (Windows NT 5.1; rv:33.0) Gecko/20100101 Firefox/33.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64; rv:50.0) Gecko/20100101 Firefox/50.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:66.0) Gecko/20100101 Firefox/66.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64; rv:52.0) Gecko/20100101 Firefox/52.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:67.0) Gecko/20100101 Firefox/67.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:50.0) Gecko/20100101 Firefox/50.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:43.0) Gecko/20100101 Firefox/43.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0')
        UA.append('Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.7.12) Gecko/20050915 Firefox/1.0.7')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:17.0) Gecko/20100101 Firefox/17.0')
        UA.append('Mozilla/5.0 (Windows NT 6.0; rv:34.0) Gecko/20100101 Firefox/34.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64; rv:54.0) Gecko/20100101 Firefox/54.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:52.0) Gecko/20100101 Firefox/52.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:63.0) Gecko/20100101 Firefox/63.0')
        UA.append('Mozilla/5.0 (Windows NT 5.1; rv:40.0) Gecko/20100101 Firefox/40.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:42.0) Gecko/20100101 Firefox/42.0')
        UA.append('Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.7.5) Gecko/20041107 Firefox/1.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:61.0) Gecko/20100101 Firefox/61.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; rv:17.0) Gecko/20100101 Firefox/20.6.14')
        UA.append('Mozilla/5.0 (Windows NT 5.1; rv:30.0) Gecko/20100101 Firefox/30.0')
        UA.append('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10; rv:33.0) Gecko/20100101 Firefox/33.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:25.0) Gecko/20100101 Firefox/29.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; rv:52.0) Gecko/20100101 Firefox/52.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:38.0) Gecko/20100101 Firefox/38.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:60.0) Gecko/20100101 Firefox/60.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:59.0) Gecko/20100101 Firefox/59.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:47.0) Gecko/20100101 Firefox/47.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:41.0) Gecko/20100101 Firefox/41.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:45.0) Gecko/20100101 Firefox/45.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:58.0) Gecko/20100101 Firefox/58.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:62.0) Gecko/20100101 Firefox/62.0')
        UA.append('Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.7.10) Gecko/20050716 Firefox/1.0.6')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64; rv:44.0) Gecko/20100101 Firefox/44.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:58.0) Gecko/20100101 Firefox/58.0')
        UA.append('Mozilla/5.0 (Windows NT 6.3; WOW64; rv:57.0) Gecko/20100101 Firefox/57.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:63.0) Gecko/20100101 Firefox/63.0')
        UA.append('Mozilla/5.0 (Windows NT 6.3; Win64; x64; rv:58.0) Gecko/20100101 Firefox/58.0')
        UA.append('Mozilla/5.0 (Windows NT 5.1; rv:6.0.2) Gecko/20100101 Firefox/6.0.2')
        UA.append('Mozilla/5.0 (Windows NT 6.3; WOW64; rv:63.0) Gecko/20100101 Firefox/63.0')
        UA.append('Mozilla/5.0 (Windows NT 5.1; rv:29.0) Gecko/20100101 Firefox/29.0')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:65.0) Gecko/20100101 Firefox/65.0')
        UA.append('Opera/9.80 (Windows NT 6.1; WOW64) Presto/2.12.388 Version/12.18')
        UA.append('Opera/9.80 (Linux armv7l) Presto/2.12.407 Version/12.51 , D50u-D1-UHD/V1.5.16-UHD (Vizio, D50u-D1, Wireless)')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.991')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36 OPR/56.0.3051.52')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.75 Safari/537.36 OPR/36.0.2130.32')
        UA.append('Opera/9.80 (Windows NT 6.0) Presto/2.12.388 Version/12.14')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.991')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36 OPR/42.0.2393.94')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3198.0 Safari/537.36 OPR/49.0.2711.0')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36 OPR/42.0.2393.94')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.78 Safari/537.36 OPR/47.0.2631.39')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36 OPR/48.0.2685.52')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36 OPR/52.0.2871.99')
        UA.append('Mozilla/5.0 (Windows NT 5.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.112 Safari/537.36 OPR/36.0.2130.80')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.73 Safari/537.36 OPR/34.0.2036.25')
        UA.append('Opera/9.80 (Windows NT 5.1; WOW64) Presto/2.12.388 Version/12.17')
        UA.append('Opera/9.80 (Windows NT 5.1; U; ru) Presto/2.9.168 Version/11.50')
        UA.append('Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; en) Opera 8.50')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.73 Safari/537.36 OPR/34.0.2036.25')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36 OPR/52.0.2871.99')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/46.0.2490.86 Safari/537.36 OPR/33.0.1990.115')
        UA.append('Opera/9.80 (Windows NT 6.2; Win64; x64) Presto/2.12.388 Version/12.16')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.170 Safari/537.36 OPR/53.0.2907.99')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.1144')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36 OPR/48.0.2685.52')
        UA.append('Mozilla/5.0 (Linux armv7l) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36 OPR/40.0.2207.0 OMI/4.9.0.237.Martell-2.258 Model/Hisense-MT5658-SDK4-9 (Hisense;HU43K303UW;V1000.01.00a.I1207) CE-HTML/1.0 HbbTV/1.2.1 MTK5658US Hisense-MT5658-US')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.1144')
        UA.append('Mozilla/5.0 (Windows NT 6.3; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.73 Safari/537.36 OPR/34.0.2036.25')
        UA.append('Mozilla/5.0 (Windows NT 5.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.991')
        UA.append('Mozilla/5.0 (Linux; U; Android 5.0.2; zh-CN; Redmi Note 3 Build/LRX22G) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 OPR/11.2.3.102637 Mobile Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.78 Safari/537.36 OPR/47.0.2631.39')
        UA.append('Opera/9.80 (Windows NT 6.1; WOW64) Presto/2.12.388 Version/12.16')
        UA.append('Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1) Opera 7.54 [en]')
        UA.append('Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.991')
        UA.append('Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.73 Safari/537.36 OPR/34.0.2036.25')
        UA.append('Mozilla/5.0 (Windows NT 6.3; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.991')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.170 Safari/537.36 OPR/53.0.2907.99')
        UA.append('Mozilla/5.0 (Windows NT 6.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36 OPR/43.0.2442.991')
        UA.append('Opera/9.80 (Windows NT 6.1; WOW64) Presto/2.12.388 Version/12.17')
        UA.append('Mozilla/5.0 (Windows NT 6.3; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36 OPR/42.0.2393.94')
        UA.append('Opera/9.80 (Windows NT 5.1) Presto/2.12.388 Version/12.17')
        UA.append('Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36 OPR/42.0.2393.94')
        UA.append('Mozilla/5.0 (Windows NT 5.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36 OPR/42.0.2393.94')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36 OPR/52.0.2871.64')
        UA.append('Mozilla/5.0 (Windows NT 6.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36 OPR/42.0.2393.94')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36 OPR/50.0.2762.67')
        UA.append('Opera/9.00 (Windows NT 5.1; U; en)')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36 OPR/47.0.2631.71')
        UA.append('Opera/9.80 (Windows NT 5.1) Presto/2.12.388 Version/12.16')
        UA.append('Mozilla/5.0 (Windows NT 6.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.112 Safari/537.36 OPR/36.0.2130.80')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36')
        UA.append('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 5.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/46.0.2490.71 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.1 (KHTML, like Gecko) Chrome/21.0.1180.83 Safari/537.1')
        UA.append('Mozilla/5.0 (Windows NT 5.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.2; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.99 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.131 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.186 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.102 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.110 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/67.0.3396.99 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/36.0.1985.143 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/59.0.3071.115 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 5.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.112 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/42.0.2311.90 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.90 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36')
        UA.append('Mozilla/5.0 (X11; OpenBSD i386) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/36.0.1985.125 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.102 Safari/537.36')
        UA.append('Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36')        
        return random.choice(UA)
        
    def USIPGenerator(self):
        IPRanges = {}
        
        OneRange = {}
        OneRange['Start'] = '3.1.1.1'
        OneRange['Stop'] = '3.254.254.254'
        
        IPRanges[0] = OneRange
        
        OneRange = {}
        OneRange['Start'] = '4.1.1.1'
        OneRange['Stop'] = '4.254.254.254'
        
        IPRanges[1] = OneRange
        
        OneRange = {}
        OneRange['Start'] = '5.1.1.1'
        OneRange['Stop'] = '5.254.254.254'
        
        IPRanges[1] = OneRange
        
        OneRange = {}
        OneRange['Start'] = '6.1.1.1'
        OneRange['Stop'] = '6.254.254.254'
        
        IPRanges[1] = OneRange
        
        OneRange = {}
        OneRange['Start'] = '7.1.1.1'
        OneRange['Stop'] = '7.254.254.254'
        
        IPRanges[1] = OneRange
        
        RandomKey = random.choice(list(IPRanges.keys()))
            
        StartRange = IPRanges[RandomKey]['Start']
        StopRange = IPRanges[RandomKey]['Stop']
        
        StartIPs = StartRange.split('.')
        StopIPs = StopRange.split('.')
        
        FinalIP = ""
        
        for Index, Value in enumerate(StartIPs):
            FinalIP += str(random.randint(int(StartIPs[Index]), int(StopIPs[Index])))+"."
        
        return FinalIP[:-1]
        
        
    def get_url_contents(self, URL, pdata=""):
        IPAddress = self.USIPGenerator()
        headers= {
                'accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'accept-encoding':'gzip, deflate, sdch, br',
                'accept-language':'en-GB,en;q=0.8,en-US;q=0.6,ml;q=0.4',
                'cache-control':'max-age=0',
                'upgrade-insecure-requests':'1',
                'user-agent':self.RandomUserAgents(),
                'X-Forwarded-For':IPAddress,
                'Via':IPAddress
            }
    
        if pdata == "":
            Response = requests.get(URL, headers=headers)
        else:
            Response = requests.post(URL, headers=headers, data=pdata)
        return Response.text	
        
    def TimeDiff(self, SecondsDifference, Granularity=2, VeryRecent='recently.'):
        Periods = {'decade':315360000, 'year':31536000, 'month':3638000, 'week':604800, 'day':86400, 'hour':3600, 'minute':60, 'second':1}
        
        ReturnValue = ""
        
        if SecondsDifference < 5:
            return VeryRecent
        else:
            for OnePeriod, NumSeconds in Periods.items():
                if SecondsDifference >= NumSeconds:
                    NewTime = math.floor(SecondsDifference/NumSeconds)
                    SecondsDifference %= NumSeconds
                    if len(ReturnValue) > 0:
                        ReturnValue += ' '
                    ReturnValue += str(NewTime)+' '+OnePeriod
                    
                    if NewTime > 1:
                        ReturnValue += 's'
                    
                    Granularity -= 1
                if Granularity == 0:
                    break
            return ReturnValue



