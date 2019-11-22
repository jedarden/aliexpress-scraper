from subprocess import call

import time
import os

from apscheduler.schedulers.background import BackgroundScheduler

def CategoryScraper():
	call(['python', '/www/ScrapeCategories.py'])

def OrderScraper():
	call(['python', '/www/ScrapeOrders.py'])

def ProductScraper():
	call(['python', '/www/ScrapeProducts.py'])

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.configure(timezone='America/New_York')
    scheduler.add_job(CategoryScraper, 'interval', seconds=3600, max_instances=1, id='CategoryScraper', coalesce=True, misfire_grace_time=300)
    scheduler.add_job(ProductScraper, 'interval', seconds=60, max_instances=1, id='ProductScraper', coalesce=True, misfire_grace_time=10)
    scheduler.add_job(OrderScraper, 'interval', seconds=60, max_instances=1, id='OrderScraper', coalesce=True, misfire_grace_time=10)
    scheduler.start()
    print('Press Ctrl+{0} to exit'.format('Break' if os.name == 'nt' else 'C'))

    try:
        # This is here to simulate application activity (which keeps the main thread alive).
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        # Not strictly necessary if daemonic mode is enabled but should be done if possible
        scheduler.shutdown()