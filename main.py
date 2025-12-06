#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - Magazyn z importem faktur XML (Document-Invoice / Line-Item)
Obsługa: Tkinter GUI (domyślnie), fallback PySimpleGUI, lub CLI gdy brak GUI lub --cli.
Zapis stanu do inventory.json, konfiguracja w config.json w katalogu użytkownika.
"""

import os
import sys
import json
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

# --- Katalog aplikacji dla config/inventory ---
if os.name == 'nt':
    APP_DIR = os.path.join(os.environ.get('APPDATA'), "Magazyn")
else:
    APP_DIR = os.path.expanduser("~/.magazyn")
os.makedirs(APP_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(APP_DIR, 'config.json')
INVENTORY_FILE = os.path.join(APP_DIR, 'inventory.json')

# --- Próba importu GUI ---
GUI_LIBRARY = None
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    GUI_LIBRARY = 'tkinter'
except Exception:
    try:
        import PySimpleGUI as sg
        GUI_LIBRARY = 'pysimplegui'
    except Exception:
        GUI_LIBRARY = None

# --- Domyślna konfiguracja ---
default_config = {
    "margin": 0.30,
    "sync_server_url": "",
    "shared_file_path": os.path.join(APP_DIR, "shared_inventory.json")
}

# --- Wczytanie lub utworzenie config ---
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception:
        config = default_config.copy()
else:
    config = default_config.copy()
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

MARGIN = float(config.get('margin', 0.30))

# --- Model ---
class Item:
    def __init__(self, name: str, category: str, quantity: int = 0, purchase_price: float = 0.0, margin: float = MARGIN, barcode: str = None):
        self.name = name
        self.category = category
        self.quantity = int(quantity)
        self.purchase_price = float(purchase_price)
        self.sale_price = round(self.purchase_price * (1 + margin), 2)
        self.barcode = barcode

    def to_dict(self):
        return {
            'name': self.name,
            'category': self.category,
            'quantity': self.quantity,
            'purchase_price': self.purchase_price,
            'sale_price': self.sale_price,
            'barcode': self.barcode
        }

    def __repr__(self):
        return f"{self.name} ({self.category}) - {self.quantity} szt. | Zakup: {self.purchase_price} zł | Sprzed: {self.sale_price} zł | EAN:{self.barcode}"

class Inventory:
    def __init__(self, storage_path=INVENTORY_FILE):
        self.storage_path = storage_path
        self.items = []
        self.load()

    def save(self):
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump([it.to_dict() for it in self.items], f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Błąd zapisu inventory:", e)

    def load(self):
        self.items = []
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for d in data:
                    it = Item(d.get('name',''), d.get('category','akcesorium'), d.get('quantity',0), d.get('purchase_price',0.0), margin=MARGIN, barcode=d.get('barcode'))
                    it.sale_price = d.get('sale_price', it.sale_price)
                    self.items.append(it)
            except Exception as e:
                print("Błąd podczas ładowania inventory.json:", e)

    def find_by_barcode(self, barcode):
        if barcode is None:
            return None
        barcode = str(barcode)
        for it in self.items:
            if it.barcode == barcode:
                return it
        return None

    def find_by_name(self, name):
        for it in self.items:
            if it.name.lower() == name.lower():
                return it
        return None

    def add_item(self, name, category, quantity=0, barcode=None, purchase_price=0.0, margin=MARGIN):
        if barcode:
            existing = self.find_by_barcode(barcode)
            if existing:
                existing.quantity += int(quantity)
                if purchase_price:
                    existing.purchase_price = float(purchase_price)
                    existing.sale_price = round(existing.purchase_price * (1 + margin), 2)
                self.save()
                return existing
        existing_name = self.find_by_name(name)
        if existing_name and not barcode:
            existing_name.quantity += int(quantity)
            if purchase_price:
                existing_name.purchase_price = float(purchase_price)
                existing_name.sale_price = round(existing_name.purchase_price * (1 + margin), 2)
            self.save()
            return existing_name

        it = Item(name, category, int(quantity), float(purchase_price), margin, barcode)
        self.items.append(it)
        self.save()
        return it

    def reduce_stock_by_barcode(self, barcode, qty):
        it = self.find_by_barcode(barcode)
        if not it:
            return None
        it.quantity = max(0, it.quantity - int(qty))
        self.save()
        return it

    def edit_prices(self, barcode, purchase_price=None, margin=None):
        it = self.find_by_barcode(barcode)
        if not it:
            return None
        if purchase_price is not None:
            it.purchase_price = float(purchase_price)
        if margin is not None:
            it.sale_price = round(it.purchase_price * (1 + float(margin)), 2)
        else:
            it.sale_price = round(it.purchase_price * 1.3, 2)
        self.save()
        return it

    def import_invoice_xml(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(filepath)

        tree = ET.parse(filepath)
        root = tree.getroot()
        lines_parent = root.find('.//Invoice-Lines') or root.find('.//InvoiceLines')
        count = 0
        if lines_parent is not None:
            for line in lines_parent.findall('.//Line'):
                li = line.find('.//Line-Item') or line
                ean = (li.findtext('EAN') or li.findtext('ean') or '').strip() or None
                name = (li.findtext('ItemDescription') or 'Brak nazwy').strip()
                qty_text = li.findtext('InvoiceQuantity') or '0'
                price_text = li.findtext('InvoiceUnitNetPrice') or '0'
                try:
                    qty = int(Decimal(qty_text.replace(',', '.')))
                except Exception:
                    qty = int(float(qty_text.replace(',', '.')))
                try:
                    purchase_price = float(Decimal(price_text.replace(',', '.')))
                except Exception:
                    purchase_price = float(price_text.replace(',', '.'))
                self.add_item(name, 'akcesorium', qty, ean, purchase_price)
                count += 1
        else:
            raise ValueError("Nie znaleziono sekcji Invoice-Lines w pliku XML")
        return count

# --- CLI / GUI selection ---
def main():
    inv = Inventory()
    use_cli = '--cli' in sys.argv or GUI_LIBRARY is None
    if not use_cli and GUI_LIBRARY == 'tkinter':
        from tkinter_main import run_tkinter  # możesz wyodrębnić GUI do osobnego pliku, opcjonalnie
        run_tkinter(inv)
    elif not use_cli and GUI_LIBRARY == 'pysimplegui':
        from pysimplegui_main import run_pysimplegui
        run_pysimplegui(inv)
    else:
        # Tryb CLI
        print("Uruchomiono w trybie tekstowym (CLI)")
        while True:
            cmd = input("> ").strip().lower()
            if cmd in ('exit','quit'):
                break
            elif cmd == 'list':
                for it in inv.items:
                    print(it)
            elif cmd.startswith('import'):
                parts = cmd.split(maxsplit=1)
                if len(parts) != 2:
                    print("Użyj: import ścieżka_do_pliku.xml")
                    continue
                try:
                    cnt = inv.import_invoice_xml(parts[1])
                    print(f"Zaimportowano {cnt} pozycji.")
                except Exception as e:
                    print("Błąd importu:", e)
            elif cmd == 'add':
                n = input("Nazwa: "); c = input("Kategoria: ") or 'akcesorium'
                q = int(input("Ilość: ") or 0); p = float(input("Cena zakupu: ") or 0.0)
                b = input("EAN: ") or None
                inv.add_item(n,c,q,b,p)
                print("Dodano.")
            elif cmd == 'reduce':
                b = input("EAN: "); q = int(input("Ile: ") or 1)
                r = inv.reduce_stock_by_barcode(b,q)
                if r: print("Zaktualizowano:", r)
                else: print("Nie znaleziono EAN.")
            elif cmd == 'edit':
                b = input("EAN: "); p = float(input("Cena zakupu: ") or 0.0); m = float(input("Marża (np. 0.3): ") or 0.3)
                r = inv.edit_prices(b,p,m)
                if r: print("Zaktualizowano ceny:", r)
                else: print("Nie znaleziono produktu.")
            elif cmd == 'help':
                print("Dostępne polecenia: list, import <plik>, add, reduce, edit, exit")
            else:
                print("Nieznane polecenie. Wpisz 'help'.")

if __name__ == '__main__':
    main()
