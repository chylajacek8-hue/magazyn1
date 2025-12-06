#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main.py - Magazyn z GUI (Tkinter / PySimpleGUI fallback) i CLI fallback.
Funkcje:
 - import faktury XML (Invoice-Lines -> Line -> Line-Item)
 - edycja pozycji (nazwa, kategoria, ilość, EAN, cena zakup, cena sprzedaży, marża)
 - zdejmowanie ze stanu (wybór z listy lub po EAN)
 - zapis/odczyt inventory.json
"""

import os
import json
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

CONFIG_FILE = 'config.json'
INVENTORY_FILE = 'inventory.json'

# --- Load/create config ---
default_config = {"margin": 0.30, "sync_server_url": "", "shared_file_path": "shared_inventory.json"}
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

DEFAULT_MARGIN = float(config.get('margin', 0.30))

# --- GUI selection ---
GUI = None
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    GUI = 'tkinter'
except Exception:
    try:
        import PySimpleGUI as sg
        GUI = 'pysimplegui'
    except Exception:
        GUI = None

# --- Models ---
class Item:
    def __init__(self, name, category='akcesorium', quantity=0, purchase_price=0.0, sale_price=None, margin=DEFAULT_MARGIN, barcode=None):
        self.name = name
        self.category = category
        self.quantity = int(quantity)
        self.purchase_price = float(purchase_price)
        self.margin = float(margin)
        # sale_price: if provided used, else computed from purchase_price and margin
        if sale_price is not None:
            self.sale_price = float(sale_price)
        else:
            try:
                self.sale_price = round(self.purchase_price * (1 + self.margin), 2)
            except Exception:
                self.sale_price = 0.0
        self.barcode = barcode if barcode is not None else None

    def to_dict(self):
        return {
            'name': self.name,
            'category': self.category,
            'quantity': self.quantity,
            'purchase_price': self.purchase_price,
            'sale_price': self.sale_price,
            'margin': self.margin,
            'barcode': self.barcode
        }

    def __repr__(self):
        return f"{self.name} ({self.category}) - {self.quantity} szt. | Zakup: {self.purchase_price} zł | Sprzed: {self.sale_price} zł | EAN:{self.barcode}"

class Inventory:
    def __init__(self, path=INVENTORY_FILE):
        self.path = path
        self.items = []
        self.load()

    def save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump([it.to_dict() for it in self.items], f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Błąd zapisu inventory:", e)

    def load(self):
        self.items = []
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for d in data:
                    it = Item(
                        name=d.get('name',''),
                        category=d.get('category','akcesorium'),
                        quantity=d.get('quantity',0),
                        purchase_price=d.get('purchase_price',0.0),
                        sale_price=d.get('sale_price', None),
                        margin=d.get('margin', DEFAULT_MARGIN),
                        barcode=d.get('barcode', None)
                    )
                    self.items.append(it)
            except Exception as e:
                print("Błąd ładowania inventory.json:", e)

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

    def add_item(self, name, category='akcesorium', quantity=0, barcode=None, purchase_price=0.0, sale_price=None, margin=DEFAULT_MARGIN):
        # if barcode exists, update quantity and optionally price
        if barcode:
            existing = self.find_by_barcode(barcode)
            if existing:
                existing.quantity += int(quantity)
                if purchase_price:
                    existing.purchase_price = float(purchase_price)
                if sale_price is not None:
                    existing.sale_price = float(sale_price)
                else:
                    existing.margin = float(margin)
                    existing.sale_price = round(existing.purchase_price * (1 + existing.margin), 2)
                self.save()
                return existing
        # try by name if barcode not provided
        if not barcode:
            existing_name = self.find_by_name(name)
            if existing_name:
                existing_name.quantity += int(quantity)
                if purchase_price:
                    existing_name.purchase_price = float(purchase_price)
                if sale_price is not None:
                    existing_name.sale_price = float(sale_price)
                else:
                    existing_name.margin = float(margin)
                    existing_name.sale_price = round(existing_name.purchase_price * (1 + existing_name.margin), 2)
                self.save()
                return existing_name
        item = Item(name=name, category=category, quantity=quantity, purchase_price=purchase_price, sale_price=sale_price, margin=margin, barcode=barcode)
        self.items.append(item)
        self.save()
        return item

    def edit_item(self, barcode_or_name, **kwargs):
        it = self.find_by_barcode(barcode_or_name) or self.find_by_name(barcode_or_name)
        if not it:
            return None
        # allowed kwargs: name, category, quantity, purchase_price, sale_price, margin, barcode
        if 'name' in kwargs and kwargs['name'] is not None:
            it.name = kwargs['name']
        if 'category' in kwargs and kwargs['category'] is not None:
            it.category = kwargs['category']
        if 'quantity' in kwargs and kwargs['quantity'] is not None:
            it.quantity = int(kwargs['quantity'])
        if 'purchase_price' in kwargs and kwargs['purchase_price'] is not None:
            it.purchase_price = float(kwargs['purchase_price'])
        if 'margin' in kwargs and kwargs['margin'] is not None:
            it.margin = float(kwargs['margin'])
            it.sale_price = round(it.purchase_price * (1 + it.margin), 2)
        if 'sale_price' in kwargs and kwargs['sale_price'] is not None:
            it.sale_price = float(kwargs['sale_price'])
        if 'barcode' in kwargs and kwargs['barcode'] is not None:
            it.barcode = kwargs['barcode']
        self.save()
        return it

    def reduce_stock_by_barcode(self, barcode, qty):
        it = self.find_by_barcode(barcode)
        if not it:
            return None
        it.quantity = max(0, it.quantity - int(qty))
        self.save()
        return it

    def import_invoice_xml(self, filepath):
        """
        Parse provided invoice XML format (Document-Invoice -> Invoice-Lines -> Line -> Line-Item)
        extract EAN, ItemDescription, InvoiceQuantity, InvoiceUnitNetPrice
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(filepath)
        tree = ET.parse(filepath)
        root = tree.getroot()
        lines_parent = root.find('.//Invoice-Lines')
        if lines_parent is None:
            lines_parent = root.find('.//InvoiceLines')
        if lines_parent is None:
            raise ValueError("Nie znaleziono sekcji Invoice-Lines w pliku XML")
        count = 0
        for line in lines_parent.findall('.//Line'):
            li = line.find('.//Line-Item') or line
            ean = (li.findtext('EAN') or li.findtext('ean') or '').strip() or None
            name = (li.findtext('ItemDescription') or li.findtext('ItemDescription') or li.findtext('ItemDescription')) or 'Brak nazwy'
            name = name.strip()
            qty_text = li.findtext('InvoiceQuantity') or '0'
            qty = 0
            try:
                qty = int(Decimal(qty_text.strip().replace(',', '.')))
            except Exception:
                try:
                    qty = int(float(qty_text.strip().replace(',', '.')))
                except Exception:
                    qty = 0
            price_text = li.findtext('InvoiceUnitNetPrice') or '0'
            try:
                purchase_price = float(Decimal(price_text.strip().replace(',', '.')))
            except Exception:
                try:
                    purchase_price = float(price_text.strip().replace(',', '.'))
                except Exception:
                    purchase_price = 0.0
            category = 'akcesorium'
            self.add_item(name=name, category=category, quantity=qty, barcode=ean, purchase_price=purchase_price)
            count += 1
        return count

# --- Tkinter GUI implementation ---
def run_tkinter(inv: Inventory):
    root = tk.Tk()
    root.title("Magazyn - edycja i EAN import")
    root.geometry("1000x600")

    cols = ("Nazwa","Kategoria","Ilość","Cena zakupu","Cena sprzedaży","EAN")
    tree = ttk.Treeview(root, columns=cols, show='headings', selectmode='browse')
    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, width=150, anchor='w')
    tree.pack(fill='both', expand=True, padx=6, pady=6)

    def refresh():
        for r in tree.get_children():
            tree.delete(r)
        for it in inv.items:
            tree.insert('', 'end', values=(it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode))

    # Buttons frame
    fb = tk.Frame(root)
    fb.pack(fill='x', padx=6, pady=6)

    def import_click():
        path = filedialog.askopenfilename(title="Wybierz fakturę XML", filetypes=[("XML", "*.xml"), ("Wszystkie","*.*")])
        if not path:
            return
        try:
            cnt = inv.import_invoice_xml(path)
            messagebox.showinfo("Import", f"Zaimportowano {cnt} pozycji.")
            refresh()
        except Exception as e:
            messagebox.showerror("Błąd importu", str(e))

    def add_click():
        win = tk.Toplevel(root); win.title("Dodaj produkt")
        labels = ["Nazwa","Kategoria","Ilość","Cena zakupu","Cena sprzedaży (opcjonalna)","EAN"]
        entries = {}
        for i, lbl in enumerate(labels):
            tk.Label(win, text=lbl).grid(row=i, column=0, sticky='w', padx=4, pady=2)
            e = tk.Entry(win); e.grid(row=i, column=1, sticky='we', padx=4, pady=2)
            entries[lbl] = e
        def save():
            try:
                name = entries["Nazwa"].get().strip()
                cat = entries["Kategoria"].get().strip() or "akcesorium"
                qty = int(entries["Ilość"].get().strip() or "0")
                p = float(entries["Cena zakupu"].get().strip() or "0")
                sp_text = entries["Cena sprzedaży (opcjonalna)"].get().strip()
                sp = float(sp_text) if sp_text else None
                ean = entries["EAN"].get().strip() or None
                inv.add_item(name=name, category=cat, quantity=qty, barcode=ean, purchase_price=p, sale_price=sp)
                refresh(); win.destroy()
            except Exception as ex:
                messagebox.showerror("Błąd", str(ex))
        tk.Button(win, text="Zapisz", command=save).grid(row=len(labels), column=0, columnspan=2, pady=6)

    def edit_click():
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("Uwaga","Wybierz produkt z listy")
            return
        vals = tree.item(sel[0])['values']
        # find item by barcode or by name
        ean = vals[5]
        it = inv.find_by_barcode(ean) or inv.find_by_name(vals[0])
        if not it:
            messagebox.showerror("Błąd","Nie znaleziono produktu")
            return
        win = tk.Toplevel(root); win.title("Edytuj produkt")
        labels = ["Nazwa","Kategoria","Ilość","Cena zakupu","Cena sprzedaży","Marża (%)","EAN"]
        entries = {}
        defaults = [it.name, it.category, str(it.quantity), str(it.purchase_price), str(it.sale_price), str(int(it.margin*100)), it.barcode or ""]
        for i, lbl in enumerate(labels):
            tk.Label(win, text=lbl).grid(row=i, column=0, sticky='w', padx=4, pady=2)
            e = tk.Entry(win); e.grid(row=i, column=1, sticky='we', padx=4, pady=2)
            e.insert(0, defaults[i])
            entries[lbl] = e
        def save():
            try:
                name = entries["Nazwa"].get().strip()
                cat = entries["Kategoria"].get().strip() or "akcesorium"
                qty = int(entries["Ilość"].get().strip() or "0")
                p = float(entries["Cena zakupu"].get().strip() or "0")
                sale_text = entries["Cena sprzedaży"].get().strip()
                sale = float(sale_text) if sale_text else None
                margin_percent = float(entries["Marża (%)"].get().strip() or "30")/100.0
                ean_new = entries["EAN"].get().strip() or None
                inv.edit_item(it.barcode or it.name, name=name, category=cat, quantity=qty, purchase_price=p, sale_price=sale, margin=margin_percent, barcode=ean_new)
                refresh(); win.destroy()
            except Exception as ex:
                messagebox.showerror("Błąd", str(ex))
        tk.Button(win, text="Zapisz", command=save).grid(row=len(labels), column=0, columnspan=2, pady=6)

    def reduce_click():
        win = tk.Toplevel(root); win.title("Zdejmij ze stanu")
        tk.Label(win, text="EAN:").grid(row=0,column=0, sticky='w')
        e_ean = tk.Entry(win); e_ean.grid(row=0,column=1)
        tk.Label(win, text="Ile sztuk:").grid(row=1,column=0, sticky='w')
        e_qty = tk.Entry(win); e_qty.grid(row=1,column=1)
        def do_reduce():
            try:
                ean = e_ean.get().strip() or None
                if not ean:
                    messagebox.showwarning("Uwaga","Podaj EAN")
                    return
                qty = int(e_qty.get().strip() or "1")
                res = inv.reduce_stock_by_barcode(ean, qty)
                if res:
                    messagebox.showinfo("OK", f"Zedjęto {qty} szt. z {res.name}. Nowy stan: {res.quantity}")
                    refresh(); win.destroy()
                else:
                    messagebox.showwarning("Nie znaleziono", "Nie znaleziono produktu o podanym EAN")
            except Exception as ex:
                messagebox.showerror("Błąd", str(ex))
        tk.Button(win, text="Zapisz", command=do_reduce).grid(row=2,column=0,columnspan=2, pady=6)

    tk.Button(fb, text="Import faktury XML", command=import_click).pack(side='left', padx=4)
    tk.Button(fb, text="Dodaj produkt", command=add_click).pack(side='left', padx=4)
    tk.Button(fb, text="Edytuj produkt", command=edit_click).pack(side='left', padx=4)
    tk.Button(fb, text="Zdejmij po EAN", command=reduce_click).pack(side='left', padx=4)
    tk.Button(fb, text="Odśwież", command=refresh).pack(side='left', padx=4)
    tk.Button(fb, text="Zamknij", command=root.destroy).pack(side='right', padx=4)

    refresh()
    root.mainloop()

# --- PySimpleGUI implementation ---
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
        [sg.Text("Magazyn - edycja i import EAN", font=("Any",14))],
        [sg.Table(values=data, headings=headings, auto_size_columns=True, display_row_numbers=False, num_rows=20, key='-TABLE-', enable_events=True)],
        [sg.Button("Import XML"), sg.Button("Dodaj"), sg.Button("Edytuj"), sg.Button("Zdejmij"), sg.Button("Odśwież"), sg.Button("Zamknij")]
    ]
    window = sg.Window("Magazyn", layout, finalize=True)
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Zamknij'):
            break
        if event == 'Odśwież':
            data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
            window['-TABLE-'].update(values=data)
        elif event == 'Import XML':
            path = sg.popup_get_file('Wybierz plik XML', file_types=(('XML Files','*.xml'),))
            if path:
                try:
                    cnt = inv.import_invoice_xml(path)
                    sg.popup('Import', f'Zaimportowano {cnt} pozycji.')
                    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
                    window['-TABLE-'].update(values=data)
                except Exception as e:
                    sg.popup_error('Błąd importu', str(e))
        elif event == 'Dodaj':
            f_layout = [
                [sg.Text('Nazwa'), sg.Input(key='-N-')],
                [sg.Text('Kategoria'), sg.Input(key='-C-')],
                [sg.Text('Ilość'), sg.Input(key='-Q-')],
                [sg.Text('Cena zakupu'), sg.Input(key='-P-')],
                [sg.Text('Cena sprzedaży (opc.)'), sg.Input(key='-SP-')],
                [sg.Text('EAN'), sg.Input(key='-B-')],
                [sg.Button('Zapisz'), sg.Button('Anuluj')]
            ]
            fwin = sg.Window('Dodaj produkt', f_layout)
            fev, fvals = fwin.read()
            if fev == 'Zapisz':
                try:
                    inv.add_item(name=fvals['-N-'], category=fvals['-C-'] or 'akcesorium', quantity=int(fvals['-Q-'] or 0),
                                 barcode=fvals['-B-'] or None, purchase_price=float(fvals['-P-'] or 0.0),
                                 sale_price=float(fvals['-SP-']) if fvals['-SP-'] else None)
                    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
                    window['-TABLE-'].update(values=data)
                except Exception as e:
                    sg.popup_error('Błąd', str(e))
            fwin.close()
        elif event == 'Edytuj':
            sel = values['-TABLE-']
            if not sel:
                sg.popup('Uwaga','Wybierz wiersz w tabeli')
                continue
            row = sel[0]; it = inv.items[row]
            form = [
                [sg.Text('Nazwa'), sg.Input(it.name, key='-N-')],
                [sg.Text('Kategoria'), sg.Input(it.category, key='-C-')],
                [sg.Text('Ilość'), sg.Input(str(it.quantity), key='-Q-')],
                [sg.Text('Cena zakupu'), sg.Input(str(it.purchase_price), key='-P-')],
                [sg.Text('Cena sprzedaży'), sg.Input(str(it.sale_price), key='-SP-')],
                [sg.Text('Marża (%)'), sg.Input(str(int(it.margin*100)), key='-M-')],
                [sg.Text('EAN'), sg.Input(it.barcode or '', key='-B-')],
                [sg.Button('Zapisz'), sg.Button('Anuluj')]
            ]
            fwin = sg.Window('Edytuj produkt', form)
            fev, fvals = fwin.read()
            if fev == 'Zapisz':
                try:
                    sale_val = fvals['-SP-']
                    sale = float(sale_val) if sale_val else None
                    margin_val = float(fvals['-M-'])/100.0
                    inv.edit_item(it.barcode or it.name, name=fvals['-N-'], category=fvals['-C-'], quantity=int(fvals['-Q-']),
                                  purchase_price=float(fvals['-P-']), sale_price=sale, margin=margin_val, barcode=fvals['-B-'] or None)
                    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
                    window['-TABLE-'].update(values=data)
                except Exception as e:
                    sg.popup_error('Błąd', str(e))
            fwin.close()
        elif event == 'Zdejmij':
            ean = sg.popup_get_text('EAN:'); q = sg.popup_get_text('Ile sztuk zdjąć?', default_text='1')
            if ean and q:
                try:
                    inv.reduce_stock_by_barcode(ean, int(q))
                    data = [[it.name, it.category, it.quantity, it.purchase_price, it.sale_price, it.barcode] for it in inv.items]
                    window['-TABLE-'].update(values=data)
                except Exception as e:
                    sg.popup_error('Błąd', str(e))
    window.close()

# --- CLI fallback ---
def run_cli(inv: Inventory):
    print("=== Magazyn (tryb tekstowy) ===")
    print("Komendy: list, import <plik>, add, edit, reduce, save, exit")
    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        if cmd == 'exit':
            break
        if cmd == 'list':
            for it in inv.items:
                print(it)
        elif cmd.startswith('import '):
            _, path = cmd.split(' ', 1)
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
        elif cmd == 'edit':
            key = input("EAN lub nazwa produktu: ")
            it = inv.find_by_barcode(key) or inv.find_by_name(key)
            if not it:
                print("Nie znaleziono.")
                continue
            print("Aktualne:", it)
            n = input(f"Nazwa [{it.name}]: ") or it.name
            c = input(f"Kategoria [{it.category}]: ") or it.category
            q = input(f"Ilość [{it.quantity}]: ") or str(it.quantity)
            p = input(f"Cena zakupu [{it.purchase_price}]: ") or str(it.purchase_price)
            sp = input(f"Cena sprzedaży [{it.sale_price}]: ") or str(it.sale_price)
            m = input(f"Marża% [{int(it.margin*100)}]: ") or str(int(it.margin*100))
            b = input(f"EAN [{it.barcode}]: ") or it.barcode
            inv.edit_item(it.barcode or it.name, name=n, category=c, quantity=int(q), purchase_price=float(p), sale_price=float(sp), margin=float(m)/100.0, barcode=b)
            print("Zapisano.")
        elif cmd == 'reduce':
            b = input("EAN: "); q = int(input("Ile: ") or 1)
            r = inv.reduce_stock_by_barcode(b, q)
            if r:
                print("Zaktualizowano:", r)
            else:
                print("Nie znaleziono.")
        elif cmd == 'save':
            inv.save(); print("Zapisano.")
        else:
            print("Nieznane polecenie.")

# --- Main ---
def main():
    inv = Inventory()
    if GUI == 'tkinter':
        run_tkinter(inv)
    elif GUI == 'pysimplegui':
        run_pysimplegui(inv)
    else:
        print("Brak GUI: uruchamiam tryb tekstowy.")
        run_cli(inv)

if __name__ == '__main__':
    main()
