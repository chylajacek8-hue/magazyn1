#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - Magazyn z importem faktur XML (format Document-Invoice z Invoice-Lines -> Line -> Line-Item)
Obsługa: Tkinter GUI (domyślnie), fallback PySimpleGUI, lub CLI gdy brak GUI.
Zapis stanu do inventory.json, konfiguracja w config.json.
"""

import os
import json
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

# Próba importu GUI - najpierw tkinter, jeśli nie ma -> PySimpleGUI, jeśli nie -> CLI
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

CONFIG_FILE = 'config.json'
INVENTORY_FILE = 'inventory.json'

# Domyślna konfiguracja
default_config = {
    "margin": 0.30,
    "sync_server_url": "",
    "shared_file_path": "shared_inventory.json"
}

# Load or create config
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
                    # zachowaj sale_price jeśli zapisane
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
        # jeśli barcode istnieje -> aktualizuj
        if barcode:
            existing = self.find_by_barcode(barcode)
            if existing:
                existing.quantity += int(quantity)
                if purchase_price:
                    existing.purchase_price = float(purchase_price)
                    existing.sale_price = round(existing.purchase_price * (1 + margin), 2)
                self.save()
                return existing
        # jeśli brak barcode -> spróbuj dopasować po nazwie i kategorii
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
        """
        Parsuje fakturę w formacie podobnym do przykładu:
        Document-Invoice -> Invoice-Lines -> Line -> Line-Item
        Z każdego Line-Item pobiera EAN, ItemDescription, InvoiceQuantity, InvoiceUnitNetPrice
        Zwraca liczbę zaimportowanych pozycji.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(filepath)

        tree = ET.parse(filepath)
        root = tree.getroot()

        # znajdź Invoice-Lines
        lines_parent = root.find('.//Invoice-Lines')
        if lines_parent is None:
            # spróbuj alternatywnie InvoiceLines
            lines_parent = root.find('.//InvoiceLines')
        count = 0
        if lines_parent is not None:
            for line in lines_parent.findall('.//Line'):
                li = line.find('.//Line-Item')
                if li is None:
                    # czasem elementy mogą być bez Line-Item, wtedy używamy line jako item
                    li = line
                # odczyt pól bezpiecznie
                ean = (li.findtext('EAN') or li.findtext('ean') or '').strip() or None
                name = (li.findtext('ItemDescription') or li.findtext('ItemDescription') or li.findtext('ItemDescription') or li.findtext('ItemDescription') or li.findtext('ItemDescription') or li.findtext('ItemDescription') or li.findtext('ItemDescription') )
                # above duplication harmless; but safe fallback
                if name is None:
                    name = li.findtext('ItemDescription') or li.findtext('ItemDescription') or li.findtext('ItemDescription')
                if name:
                    name = name.strip()
                else:
                    name = 'Brak nazwy'
                qty_text = li.findtext('InvoiceQuantity') or li.findtext('InvoiceQuantity') or li.findtext('InvoiceQuantity') or li.findtext('InvoiceQuantity') or li.findtext('InvoiceQuantity')
                # robust parse number
                qty = 0
                if qty_text:
                    try:
                        # replace comma with dot if needed
                        qty = int(Decimal(qty_text.strip().replace(',', '.')))
                    except (InvalidOperation, ValueError):
                        try:
                            qty = int(float(qty_text.strip().replace(',', '.')))
                        except Exception:
                            qty = 0
                price_text = li.findtext('InvoiceUnitNetPrice') or li.findtext('InvoiceUnitNetPrice') or li.findtext('InvoiceUnitNetPrice')
                purchase_price = 0.0
                if price_text:
                    try:
                        purchase_price = float(Decimal(price_text.strip().replace(',', '.')))
                    except Exception:
                        try:
                            purchase_price = float(price_text.strip().replace(',', '.'))
                        except Exception:
                            purchase_price = 0.0
                # category: nie ma w przykładowym pliku, użyjemy 'akcesorium' jako domyślne
                category = 'akcesorium'
                # Dodajemy do magazynu (scalując po EAN jeśli istnieje)
                self.add_item(name, category, qty, ean, purchase_price)
                count += 1
        else:
            # Nie znaleziono sekcji Invoice-Lines
            raise ValueError("Nie znaleziono sekcji Invoice-Lines w pliku XML")

        return count

# --- GUI / CLI ---

def run_tkinter(inv: Inventory):
    root = tk.Tk()
    root.title("Magazyn - import EAN z faktury")
    root.geometry("900x520")

    # Treeview
    cols = ("Nazwa", "Kategoria", "Ilość", "Cena zakupu", "Cena sprzedaży", "EAN")
    tree = ttk.Treeview(root, columns=cols, show='headings')
    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, width=140)
    tree.pack(fill='both', expand=True, padx=5, pady=5)

    def refresh():
        for r in tree.get_children():
            tree.delete(r)
        for it in inv.items:
            tree.insert('', 'end', values=(it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode))

    # Buttons
    frame = tk.Frame(root)
    frame.pack(fill='x', padx=5, pady=5)
    def on_import():
        path = filedialog.askopenfilename(title="Wybierz fakturę XML", filetypes=[("XML files","*.xml"),("All files","*.*")])
        if not path:
            return
        try:
            cnt = inv.import_invoice_xml(path)
            messagebox.showinfo("Import", f"Zaimportowano {cnt} pozycji z pliku.")
            refresh()
        except Exception as e:
            messagebox.showerror("Błąd importu", str(e))

    def on_add():
        win = tk.Toplevel(root)
        win.title("Dodaj produkt ręcznie")
        labels = ["Nazwa","Kategoria","Ilość","Cena zakupu","EAN"]
        entries = {}
        for i, lbl in enumerate(labels):
            tk.Label(win, text=lbl).grid(row=i, column=0, sticky='w', padx=4, pady=2)
            e = tk.Entry(win)
            e.grid(row=i, column=1, sticky='we', padx=4, pady=2)
            entries[lbl] = e
        def save():
            try:
                name = entries["Nazwa"].get().strip()
                cat = entries["Kategoria"].get().strip() or "akcesorium"
                qty = int(entries["Ilość"].get().strip() or "0")
                price = float(entries["Cena zakupu"].get().strip() or "0")
                ean = entries["EAN"].get().strip() or None
                inv.add_item(name, cat, qty, ean, price)
                refresh()
                win.destroy()
            except Exception as ex:
                messagebox.showerror("Błąd", str(ex))
        tk.Button(win, text="Zapisz", command=save).grid(row=len(labels), column=0, columnspan=2, pady=6)

    def on_reduce_by_ean():
        win = tk.Toplevel(root)
        win.title("Zdejmij ze stanu po EAN")
        tk.Label(win, text="EAN:").grid(row=0,column=0, sticky='w')
        e_ean = tk.Entry(win); e_ean.grid(row=0,column=1)
        tk.Label(win, text="Ile sztuk:").grid(row=1,column=0, sticky='w')
        e_qty = tk.Entry(win); e_qty.grid(row=1,column=1)
        def do_reduce():
            try:
                ean = e_ean.get().strip() or None
                qty = int(e_qty.get().strip() or "1")
                res = inv.reduce_stock_by_barcode(ean, qty)
                if res:
                    messagebox.showinfo("OK", f"Zedjęto {qty} szt. z {res.name}. Nowy stan: {res.quantity}")
                    refresh()
                    win.destroy()
                else:
                    messagebox.showwarning("Nie znaleziono", "Nie znaleziono produktu o podanym EAN")
            except Exception as ex:
                messagebox.showerror("Błąd", str(ex))
        tk.Button(win, text="Zapisz", command=do_reduce).grid(row=2,column=0,columnspan=2, pady=6)

    tk.Button(frame, text="Import faktury XML", command=on_import).pack(side='left', padx=5)
    tk.Button(frame, text="Dodaj produkt", command=on_add).pack(side='left', padx=5)
    tk.Button(frame, text="Zdejmij po EAN", command=on_reduce_by_ean).pack(side='left', padx=5)
    tk.Button(frame, text="Odśwież", command=refresh).pack(side='left', padx=5)
    tk.Button(frame, text="Zamknij", command=root.destroy).pack(side='right', padx=5)

    refresh()
    root.mainloop()

def run_pysimplegui(inv: Inventory):
    try:
        import PySimpleGUI as sg
    except Exception:
        print("PySimpleGUI nie jest zainstalowane.")
        return
    sg.set_options(auto_size_buttons=True)
    headings = ['Nazwa','Kategoria','Ilość','Cena zakupu','Cena sprzedaży','EAN']
    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
    layout = [
        [sg.Text("Magazyn - import EAN z faktury", font=("Any",14))],
        [sg.Table(values=data, headings=headings, max_col_width=25, auto_size_columns=True, display_row_numbers=False, num_rows=20, key='-TABLE-', enable_events=True)],
        [sg.Button("Import XML"), sg.Button("Dodaj produkt"), sg.Button("Zdejmij po EAN"), sg.Button("Odśwież"), sg.Button("Zamknij")]
    ]
    win = sg.Window("Magazyn", layout, finalize=True)
    while True:
        event, values = win.read()
        if event in (sg.WIN_CLOSED, 'Zamknij'):
            break
        if event == 'Odśwież':
            data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
            win['-TABLE-'].update(values=data)
        elif event == 'Import XML':
            path = sg.popup_get_file('Wybierz plik XML', file_types=(('XML Files','*.xml'),))
            if path:
                try:
                    cnt = inv.import_invoice_xml(path)
                    sg.popup('Import', f'Zaimportowano {cnt} pozycji.')
                    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
                    win['-TABLE-'].update(values=data)
                except Exception as e:
                    sg.popup_error('Błąd importu', str(e))
        elif event == 'Dodaj produkt':
            form = [
                [sg.Text('Nazwa'), sg.Input(key='-N-')],
                [sg.Text('Kategoria'), sg.Input(key='-C-')],
                [sg.Text('Ilość'), sg.Input(key='-Q-')],
                [sg.Text('Cena zakupu'), sg.Input(key='-P-')],
                [sg.Text('EAN'), sg.Input(key='-B-')],
                [sg.Button('Zapisz'), sg.Button('Anuluj')]
            ]
            fwin = sg.Window('Dodaj produkt', form)
            fev, fvals = fwin.read()
            if fev == 'Zapisz':
                try:
                    inv.add_item(fvals['-N-'], fvals['-C-'] or 'akcesorium', int(fvals['-Q-'] or 0), fvals['-B-'] or None, float(fvals['-P-'] or 0.0))
                    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
                    win['-TABLE-'].update(values=data)
                except Exception as e:
                    sg.popup_error('Błąd', str(e))
            fwin.close()
        elif event == 'Zdejmij po EAN':
            sel = win['-TABLE-'].get()
            # prosty dialog
            ean = sg.popup_get_text('EAN:') 
            q = sg.popup_get_text('Ile sztuk zdjąć?', default_text='1')
            if ean and q:
                try:
                    inv.reduce_stock_by_barcode(ean, int(q))
                    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
                    win['-TABLE-'].update(values=data)
                except Exception as e:
                    sg.popup_error('Błąd', str(e))
    win.close()

def run_cli(inv: Inventory):
    print("Magazyn - tryb tekstowy")
    print("Dostępne polecenia: list, import <plik>, add, reduce, edit, exit")
    while True:
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        if cmd == 'exit':
            break
        if cmd == 'list':
            for it in inv.items:
                print(it)
        elif cmd.startswith('import'):
            parts = cmd.split(maxsplit=1)
            if len(parts) == 1:
                print("Użyj: import ścieżka_do_pliku.xml")
                continue
            path = parts[1]
            try:
                cnt = inv.import_invoice_xml(path)
                print(f"Zaimportowano {cnt} pozycji.")
            except Exception as e:
                print("Błąd importu:", e)
        elif cmd == 'add':
            n = input("Nazwa: "); c = input("Kategoria: ") or 'akcesorium'
            q = int(input("Ilość: ") or 0); p = float(input("Cena zakupu: ") or 0.0)
            b = input("EAN: ") or None
            inv.add_item(n, c, q, b, p)
            print("Dodano.")
        elif cmd == 'reduce':
            b = input("EAN: "); q = int(input("Ile: ") or 1)
            r = inv.reduce_stock_by_barcode(b, q)
            if r:
                print("Zaktualizowano:", r)
            else:
                print("Nie znaleziono EAN.")
        elif cmd == 'edit':
            b = input("EAN produktu: "); p = float(input("Nowa cena zakupu: ") or 0.0); m = float(input("Marża (np. 0.3): ") or 0.3)
            r = inv.edit_prices(b, p, m)
            if r:
                print("Zaktualizowano ceny:", r)
            else:
                print("Nie znaleziono produktu.")
        else:
            print("Nieznane polecenie.")

def main():
    inv = Inventory()
    if GUI_LIBRARY == 'tkinter':
        run_tkinter(inv)
    elif GUI_LIBRARY == 'pysimplegui':
        run_pysimplegui(inv)
    else:
        print("Brak GUI (tkinter/pySimpleGUI). Uruchamiam tryb tekstowy.")
        run_cli(inv)

if __name__ == '__main__':
    main()
