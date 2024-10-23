import csv
import re
import os
import argparse
import hashlib
from datetime import timedelta, datetime as dt
from pathlib import Path
from collections import defaultdict

parser = argparse.ArgumentParser(prog='ParsePortofolioDump',
                                 description='Parse a deGiro broker portofolio csv dump for further analysis',
                                 epilog='Made by Freek Kalter')
parser.add_argument('-o', '--output', default='out.csv',
                    help='output filename for portfolio info')
parser.add_argument('-y', '--year', type=int,
                    help='specify year to calculate dividends for')
args = parser.parse_args()


def to_float(s):
    return float(re.sub(',', '.', s))


def sort_dict_by_value(d):
    return [k[0] for k in sorted(d.items(), key=lambda item: item[1], reverse=True)]


def get_last_line(filename):
    with open(filename, 'rb') as f:
        try:  # catch OSError in case of a one line file
            f.seek(-2, os.SEEK_END)
            while f.read(1) != b'\n':
                f.seek(-2, os.SEEK_CUR)
        except OSError:
            f.seek(0)
        return f.readline().strip().decode()


def get_latest(d, filename):
    portfolios = []
    p = Path(d)
    for f in [f.name for f in p.iterdir() if f.is_file()]:
        if re.search(filename + r' \(\d+\)', f):
            portfolios.append(f)
    return p.joinpath(sorted(portfolios, key=lambda x: int(re.search(r'\((\d+)\)', x).group(1)), reverse=True)[0])


def parse_portfolio():
    last_line = get_last_line('./portfolio.log')
    products = {}
    with open(get_latest('/home/fkalter/Downloads', 'Portfolio')) as fh:
        csv_reader = csv.DictReader(fh)
        for row in csv_reader:
            if not row['Product'].startswith('CASH & CASH FUND & FTX CASH'):
                products[re.sub(r'\.', '', row['Product'])] = to_float(row['Waarde in EUR'])
                # products.append({'product': row['Product'],
                #                  'value': to_float(row['Waarde in EUR'])})
    with open(args.output, 'w') as fh:
        print('product;value', file=fh)
        for key in sort_dict_by_value(products):
            print(f'{key};{str(products[key]).replace('.', ',')}', file=fh)

    ho = hashlib.sha256()
    lines = []
    for key in sort_dict_by_value(products):
        s = f'{key};{str(products[key]).replace('.', ',')}'
        lines.append(s)
        ho.update(s.encode('utf-8'))
    if last_line != ho.hexdigest():
        with open('./portfolio.log', 'a') as fh:
            print(f'-----{dt.now().strftime("%y-%m-%d %H:%M:%S")}----------------------------', file=fh)
            for line in lines:
                print(line, file=fh)
            print(ho.hexdigest(), file=fh)

    return products


def search(transactions, date, product, description):
    delta = timedelta(days=5)
    for row in transactions:
        try:
            d = abs(dt.strptime(row['Datum'], '%d-%m-%Y') - dt.strptime(date, '%d-%m-%Y'))
        except ValueError:
            continue
        try:
            if d < delta and\
               row['Product'] == product and\
               description in row['Omschrijving']:
                return row['Bedrag']
        except KeyError:
            pass
    print(f'No {description.lower()} found for "{product}" on {date}')
    return 0


def search_valuta(transactions, valuta_date, amount):
    delta = timedelta(days=15)
    for row in transactions:
        if re.search(r'valuta debitering', row['Omschrijving'], flags=re.IGNORECASE) and\
           abs(abs(float(row['Bedrag'])) - amount) < 0.0001 and\
           abs(dt.strptime(row['Datum'], '%d-%m-%Y') - dt.strptime(valuta_date, '%d-%m-%Y')) < delta:
            return 1 / float(row['FX']) * abs(float(row['Bedrag']))
    raise ValueError


def parse_dividend(value_per_product):
    transactions = []
    with open(get_latest('/home/fkalter/Downloads/', 'Account')) as fh:
        csv_reader = csv.DictReader(fh, fieldnames=['Datum', 'Tijd', 'Valutadatum', 'Product', 'ISIN',
                                                    'Omschrijving', 'FX', 'Mutatie_cur', 'Bedrag', 'Saldo_cur', 'Saldo', 'Order Id'])
        for row in csv_reader:
            transactions.append(row)
    dividend = []
    for trans in transactions:
        if trans['Omschrijving'] == 'Dividend':
            if args.year:
                begin = dt(year=args.year, month=1, day=1)
                end = dt(year=args.year, month=12, day=31)
                transaction_date = dt.strptime(trans['Datum'], '%d-%m-%Y')
                if not (transaction_date < end and transaction_date > begin):
                    continue
            belasting = search(transactions[1:], trans['Datum'], trans['Product'], 'Dividendbelasting')
            netto = float(trans['Bedrag']) - abs(float(belasting))
            euros = netto
            try:
                if trans['Mutatie_cur'] != 'EUR':
                    euros = search_valuta(transactions, trans['Datum'], netto)
                dividend.append({'Product': re.sub(r'\.', '', trans['Product']), 'Datum': dt.strptime(trans['Datum'], '%d-%m-%Y'),
                                 'Bedrag': trans['Bedrag'], 'Belasting': belasting,
                                 'Netto': netto, 'Euro': euros})
            except ValueError:
                print('what')
                print({'Product': trans['Product'], 'Datum': trans['Datum'],
                       'Bedrag': trans['Bedrag'], 'Belasting': belasting,
                       'Netto': netto})

    total_per_product = defaultdict(int)
    for d in dividend:
        total_per_product[d['Product']] += d['Euro']
        # print(f'{d["Datum"]} {d["Product"]:<30}: {d["Bedrag"]}, {d["Belasting"]}, {d["Netto"]:.2f} , {d["Euro"]:.2f}')
        # print(f'{d["Datum"]} {d["Product"]:<30}: {d["Euro"]:.2f}')

    print(f'{"Product":<40} {"value":<8} {"total dividend":<18} {"avg/month":<10} percentage of stock value')
    for product in sort_dict_by_value(total_per_product):
        first_dividend_date = min([d['Datum'] for d in dividend if d['Product'] == product])
        avg_per_month = (total_per_product[product] / (dt.today() - first_dividend_date).days) * 30
        percentage = (total_per_product[product] / value_per_product[product[:32]]) * 100
        print(f'{product:<40} {value_per_product[product[:32]]:<8} {total_per_product[product]:<18.2f} {avg_per_month:<10.2f} {percentage:.2f}')

    print(f'\nTotal amount of dividend received: {sum([d["Euro"] for d in dividend]):.2f}')


if __name__ == '__main__':
    products = parse_portfolio()
    parse_dividend(products)
