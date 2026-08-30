"""
Beer Budget Optimizer - GUI
----------------------------
A Tkinter front-end for beer_optimizer.py. Built entirely from the
Python standard library (no pip installs needed) so it can be frozen
into a single standalone .exe with PyInstaller.

On launch, this opens four windows:
  - a Settings dialog (session/rolling/category limits and their time
    frames, in days) - must be confirmed before anything else appears
  - the main Run window
  - an editable Beers table
  - an editable Category Prices table
All data (beer list, prices, settings, purchase history) saves to this
computer's local data folder (see beer_optimizer.get_data_dir), so it
persists between runs and is never written back to a shared flash drive.

Run directly with:  python beer_optimizer_gui.py
"""

import os
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk

import beer_optimizer as core

CATEGORY_CHOICES = sorted(core.CATEGORIES)

CAP_FIELDS = [
    ("session_limit_oz", "Session limit per beer (oz)"),
    ("rolling_volume_limit_oz", "Rolling volume limit per beer (oz)"),
    ("rolling_volume_window_days", "  \u2192 time frame (days)"),
    ("rolling_category_limit_oz", "Rolling category limit (oz)"),
    ("rolling_category_window_days", "  \u2192 time frame (days)"),
]
WEIGHT_FIELDS = [
    ("weight_enjoyability_pct", "Enjoyability weight (%)"),
    ("weight_price_pct", "Price weight (%)"),
    ("weight_strength_pct", "Strength weight (%)"),
]


def _build_settings_from_vars(vars_dict: dict) -> "core.Settings | None":
    """Validate all settings fields and build a core.Settings, or show an
    error box and return None if anything is invalid."""
    values = {}
    for key, _ in CAP_FIELDS:
        raw = vars_dict[key].get().strip()
        try:
            value = int(raw)
        except ValueError:
            messagebox.showerror("Invalid entry", f"'{raw}' is not a whole number.")
            return None
        if value <= 0:
            messagebox.showerror("Invalid entry", "All limits and time frames must be greater than zero.")
            return None
        values[key] = value

    weight_values = {}
    for key, _ in WEIGHT_FIELDS:
        raw = vars_dict[key].get().strip()
        try:
            value = int(raw)
        except ValueError:
            messagebox.showerror("Invalid entry", f"'{raw}' is not a whole number.")
            return None
        if value < 0:
            messagebox.showerror("Invalid entry", "Weights cannot be negative.")
            return None
        weight_values[key] = value

    if sum(weight_values.values()) != 100:
        messagebox.showerror(
            "Invalid weights",
            f"Enjoyability + Price + Strength must add up to 100%.\n"
            f"Currently: {sum(weight_values.values())}%"
        )
        return None
    values.update(weight_values)
    return core.Settings(**values)


# ---------------------------------------------------------------------------
# Small reusable Add/Edit form dialog
# ---------------------------------------------------------------------------
class FormDialog(tk.Toplevel):
    """
    Modal form for adding/editing one row. `fields` is a list of
    (key, label, kind) tuples where kind is "text" or a list of choices
    (for a combobox). Result is stored in self.result as a dict, or
    None if the user cancelled.
    """

    def __init__(self, master, title, fields, initial=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.fields = fields
        self.vars = {}
        self.result = None
        initial = initial or {}

        for i, (key, label, kind) in enumerate(fields):
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=6)
            var = tk.StringVar(value=str(initial.get(key, "")))
            if isinstance(kind, list):  # dropdown
                widget = ttk.Combobox(self, textvariable=var, values=kind, state="readonly", width=22)
            else:
                widget = ttk.Entry(self, textvariable=var, width=25)
            widget.grid(row=i, column=1, sticky="ew", padx=8, pady=6)
            self.vars[key] = var

        btn_row = len(fields)
        btns = ttk.Frame(self)
        btns.grid(row=btn_row, column=0, columnspan=2, pady=10)
        ttk.Button(btns, text="Save", command=self._on_save).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)

        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self.destroy())
        self.wait_window(self)

    def _on_save(self):
        self.result = {key: var.get().strip() for key, var in self.vars.items()}
        self.destroy()


# ---------------------------------------------------------------------------
# Startup settings dialog - session/rolling/category caps and their windows
# ---------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    """
    Reopened mid-session via the "Change Limits..." button, when the main
    window is already visible - safe to use as a Toplevel here since it's
    transient to a real, mapped window rather than a hidden one.
    Result is stored in self.settings (a core.Settings), or None if the
    user closed/cancelled.
    """

    def __init__(self, master, initial: core.Settings):
        super().__init__(master)
        self.title("Beer Budget Optimizer - Settings")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.settings = None

        ttk.Label(
            self, text="Set the purchase limits for this session.\nThese are saved and pre-filled next time.",
            justify="left"
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))

        self.vars = {}
        row = 1
        for key, label in CAP_FIELDS:
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=4)
            var = tk.StringVar(value=str(getattr(initial, key)))
            ttk.Entry(self, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=10, pady=4)
            self.vars[key] = var
            row += 1

        ttk.Separator(self, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=8)
        row += 1
        ttk.Label(
            self, text="Scoring weights (must add up to 100%):", justify="left"
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=10)
        row += 1
        for key, label in WEIGHT_FIELDS:
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=4)
            var = tk.StringVar(value=str(getattr(initial, key)))
            ttk.Entry(self, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=10, pady=4)
            self.vars[key] = var
            row += 1

        btns = ttk.Frame(self)
        btns.grid(row=row, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Reset to defaults", command=self._reset_defaults).pack(side="left", padx=6)
        ttk.Button(btns, text="Start", command=self._on_start).pack(side="left", padx=6)

        self.bind("<Return>", lambda e: self._on_start())
        self.transient(master)
        self.lift()
        self.focus_force()
        self.grab_set()
        self.wait_window(self)

    def _reset_defaults(self):
        defaults = core.Settings()
        for key, var in self.vars.items():
            var.set(str(getattr(defaults, key)))

    def _on_start(self):
        settings = _build_settings_from_vars(self.vars)
        if settings is None:
            return
        core.save_settings(settings)
        self.settings = settings
        self.destroy()

    def _on_cancel(self):
        self.settings = None
        self.destroy()


# ---------------------------------------------------------------------------
# Startup settings screen - built directly into the (always-visible) root
# window, rather than a Toplevel dialog attached to a hidden parent. This
# avoids a Windows-specific issue where a Toplevel transient to a withdrawn,
# never-mapped root can end up positioned off-screen and never actually
# rendered, even though the process runs fine.
# ---------------------------------------------------------------------------
class SettingsFrame(ttk.Frame):
    def __init__(self, master, initial: core.Settings, on_start):
        super().__init__(master)
        self.on_start = on_start

        ttk.Label(
            self, text="Set the purchase limits for this session.\nThese are saved and pre-filled next time.",
            justify="left"
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))

        self.vars = {}
        row = 1
        for key, label in CAP_FIELDS:
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=4)
            var = tk.StringVar(value=str(getattr(initial, key)))
            ttk.Entry(self, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=10, pady=4)
            self.vars[key] = var
            row += 1

        ttk.Separator(self, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=8)
        row += 1
        ttk.Label(
            self, text="Scoring weights (must add up to 100%):", justify="left"
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=10)
        row += 1
        for key, label in WEIGHT_FIELDS:
            ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=4)
            var = tk.StringVar(value=str(getattr(initial, key)))
            ttk.Entry(self, textvariable=var, width=10).grid(row=row, column=1, sticky="w", padx=10, pady=4)
            self.vars[key] = var
            row += 1

        btns = ttk.Frame(self)
        btns.grid(row=row, column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="Reset to defaults", command=self._reset_defaults).pack(side="left", padx=6)
        ttk.Button(btns, text="Start", command=self._on_start_clicked).pack(side="left", padx=6)

        master.bind("<Return>", lambda e: self._on_start_clicked())

    def _reset_defaults(self):
        defaults = core.Settings()
        for key, var in self.vars.items():
            var.set(str(getattr(defaults, key)))

    def _on_start_clicked(self):
        settings = _build_settings_from_vars(self.vars)
        if settings is None:
            return
        core.save_settings(settings)
        self.on_start(settings)


# ---------------------------------------------------------------------------
# Beers editor
# ---------------------------------------------------------------------------
class BeersEditor(tk.Toplevel):
    COLUMNS = ["name", "enjoyability", "abv", "category"]
    HEADERS = ["Name", "Enjoyability (1-10)", "ABV (%)", "Category"]

    def __init__(self, master):
        super().__init__(master)
        self.title("Edit Beers")
        self.geometry("560x420")

        self.tree = ttk.Treeview(self, columns=self.COLUMNS, show="headings", selectmode="browse")
        for col, header in zip(self.COLUMNS, self.HEADERS):
            self.tree.heading(col, text=header)
            self.tree.column(col, width=120, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Add...", command=self.add_row).pack(side="left", padx=4)
        ttk.Button(btns, text="Edit...", command=self.edit_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete", command=self.delete_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="Reload", command=self.reload).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=self.save).pack(side="right", padx=4)

        self.reload()

    def reload(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = core.load_beer_rows(core.DEFAULT_BEERS_CSV)
        for row in rows:
            self.tree.insert("", "end", values=[row.get(c, "") for c in self.COLUMNS])

    def _rows(self):
        return [dict(zip(self.COLUMNS, self.tree.item(i)["values"])) for i in self.tree.get_children()]

    def add_row(self):
        dlg = FormDialog(self, "Add Beer", [
            ("name", "Name", "text"),
            ("enjoyability", "Enjoyability (1-10)", "text"),
            ("abv", "ABV (%)", "text"),
            ("category", "Category", CATEGORY_CHOICES),
        ])
        if dlg.result:
            if self._validate(dlg.result):
                self.tree.insert("", "end", values=[dlg.result[c] for c in self.COLUMNS])

    def edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a beer to edit first.")
            return
        item = sel[0]
        current = dict(zip(self.COLUMNS, self.tree.item(item)["values"]))
        dlg = FormDialog(self, "Edit Beer", [
            ("name", "Name", "text"),
            ("enjoyability", "Enjoyability (1-10)", "text"),
            ("abv", "ABV (%)", "text"),
            ("category", "Category", CATEGORY_CHOICES),
        ], initial=current)
        if dlg.result:
            if self._validate(dlg.result):
                self.tree.item(item, values=[dlg.result[c] for c in self.COLUMNS])

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a beer to delete first.")
            return
        if messagebox.askyesno("Confirm delete", "Delete the selected beer?"):
            self.tree.delete(sel[0])

    def _validate(self, values) -> bool:
        if not values["name"]:
            messagebox.showerror("Invalid entry", "Name cannot be blank.")
            return False
        try:
            float(values["enjoyability"])
            float(values["abv"])
        except ValueError:
            messagebox.showerror("Invalid entry", "Enjoyability and ABV must be numbers.")
            return False
        if values["category"] not in core.CATEGORIES:
            messagebox.showerror("Invalid entry", f"Category must be one of: {CATEGORY_CHOICES}")
            return False
        return True

    def save(self):
        rows = self._rows()
        if not rows:
            messagebox.showerror("Nothing to save", "Add at least one beer first.")
            return
        core.save_beer_rows(core.DEFAULT_BEERS_CSV, rows)
        messagebox.showinfo("Saved", f"Saved {len(rows)} beer(s) to:\n{core.DEFAULT_BEERS_CSV}")


# ---------------------------------------------------------------------------
# Category prices editor (fixed set of 5 categories - edit only, no add/delete)
# ---------------------------------------------------------------------------
class CategoryPricesEditor(tk.Toplevel):
    COLUMNS = ["category", "price_16", "price_32", "price_64"]
    HEADERS = ["Category", "16oz Price", "32oz Price", "64oz Price"]

    def __init__(self, master):
        super().__init__(master)
        self.title("Edit Category Prices")
        self.geometry("480x260")

        self.tree = ttk.Treeview(self, columns=self.COLUMNS, show="headings", selectmode="browse")
        for col, header in zip(self.COLUMNS, self.HEADERS):
            self.tree.heading(col, text=header)
            self.tree.column(col, width=100, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Edit...", command=self.edit_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="Reload", command=self.reload).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=self.save).pack(side="right", padx=4)

        ttk.Label(
            self, text="Leave a price blank if that size isn't offered for a category.",
            foreground="#555"
        ).pack(padx=8, pady=(0, 6), anchor="w")

        self.reload()

    def reload(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = {r["category"]: r for r in core.load_category_price_rows(core.DEFAULT_PRICES_CSV)}
        # Always show all 5 fixed categories, even if a row is somehow missing
        for category in CATEGORY_CHOICES:
            row = rows.get(category, {"category": category, "price_16": "", "price_32": "", "price_64": ""})
            self.tree.insert("", "end", values=[row.get(c, "") for c in self.COLUMNS])

    def _rows(self):
        return [dict(zip(self.COLUMNS, self.tree.item(i)["values"])) for i in self.tree.get_children()]

    def edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a category to edit first.")
            return
        item = sel[0]
        current = dict(zip(self.COLUMNS, self.tree.item(item)["values"]))
        dlg = FormDialog(self, f"Edit {current['category']} Pricing", [
            ("category", "Category", "text"),  # shown but not actually editable (see below)
            ("price_16", "16oz Price", "text"),
            ("price_32", "32oz Price", "text"),
            ("price_64", "64oz Price", "text"),
        ], initial=current)
        if dlg.result:
            # category is fixed - always keep the original value regardless of the form
            dlg.result["category"] = current["category"]
            if self._validate(dlg.result):
                self.tree.item(item, values=[dlg.result[c] for c in self.COLUMNS])

    def _validate(self, values) -> bool:
        prices_given = False
        for key in ("price_16", "price_32", "price_64"):
            val = values[key]
            if val:
                try:
                    float(val)
                    prices_given = True
                except ValueError:
                    messagebox.showerror("Invalid entry", f"{key} must be a number or blank.")
                    return False
        if not prices_given:
            messagebox.showerror("Invalid entry", "At least one size must have a price.")
            return False
        return True

    def save(self):
        core.save_category_price_rows(core.DEFAULT_PRICES_CSV, self._rows())
        messagebox.showinfo("Saved", f"Saved category prices to:\n{core.DEFAULT_PRICES_CSV}")


# ---------------------------------------------------------------------------
# Main run window
# ---------------------------------------------------------------------------
class BeerOptimizerApp:
    def __init__(self, root: tk.Tk, settings: core.Settings):
        self.root = root
        self.settings = settings
        root.title("Beer Budget Optimizer")
        root.geometry("720x600")
        root.minsize(600, 480)

        self.budget = tk.StringVar(value="100.00")
        self.save_to_history = tk.BooleanVar(value=True)

        self._build_layout()

    def _build_layout(self):
        pad = {"padx": 8, "pady": 4}

        frame_data = ttk.LabelFrame(self.root, text="Data")
        frame_data.pack(fill="x", **pad)
        ttk.Button(frame_data, text="Edit Beers...", command=self.open_beers_editor).pack(
            side="left", padx=6, pady=6)
        ttk.Button(frame_data, text="Edit Category Prices...", command=self.open_prices_editor).pack(
            side="left", padx=6, pady=6)
        ttk.Button(frame_data, text="Change Limits...", command=self.open_settings_editor).pack(
            side="left", padx=6, pady=6)
        ttk.Label(frame_data, text=f"Data folder: {core.get_data_dir()}", foreground="#555").pack(
            side="left", padx=10)

        self.limits_label = ttk.Label(self.root, foreground="#555")
        self.limits_label.pack(fill="x", padx=12)
        self._refresh_limits_label()

        frame_run = ttk.LabelFrame(self.root, text="Run")
        frame_run.pack(fill="x", **pad)
        ttk.Label(frame_run, text="Budget ($):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame_run, textvariable=self.budget, width=12).grid(row=0, column=1, sticky="w", **pad)
        ttk.Checkbutton(
            frame_run, text="Save this run to purchase history", variable=self.save_to_history
        ).grid(row=0, column=2, sticky="w", **pad)
        ttk.Button(frame_run, text="Run", command=self.run).grid(row=0, column=3, sticky="e", **pad)

        frame_out = ttk.LabelFrame(self.root, text="Results")
        frame_out.pack(fill="both", expand=True, **pad)
        self.output = scrolledtext.ScrolledText(frame_out, wrap="word", font=("Consolas", 10))
        self.output.pack(fill="both", expand=True, padx=4, pady=4)
        self.output.configure(state="disabled")

    def _refresh_limits_label(self):
        s = self.settings
        self.limits_label.configure(
            text=(f"Limits - session: {s.session_limit_oz}oz/beer  |  "
                  f"rolling: {s.rolling_volume_limit_oz}oz/beer per {s.rolling_volume_window_days}d  |  "
                  f"category: {s.rolling_category_limit_oz}oz per {s.rolling_category_window_days}d  |  "
                  f"weights: {s.weight_enjoyability_pct}/{s.weight_price_pct}/{s.weight_strength_pct} "
                  f"(enjoy/price/strength)")
        )

    def open_beers_editor(self):
        BeersEditor(self.root)

    def open_prices_editor(self):
        CategoryPricesEditor(self.root)

    def open_settings_editor(self):
        dlg = SettingsDialog(self.root, self.settings)
        if dlg.settings is not None:
            self.settings = dlg.settings
            self._refresh_limits_label()

    def _print(self, text=""):
        self.output.configure(state="normal")
        self.output.insert("end", text + "\n")
        self.output.configure(state="disabled")
        self.output.see("end")

    def run(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

        try:
            budget = float(self.budget.get())
        except ValueError:
            messagebox.showerror("Invalid budget", "Budget must be a number.")
            return

        try:
            now = datetime.now()
            category_prices = core.load_category_prices(core.DEFAULT_PRICES_CSV)
            beers = core.load_beers_from_csv(core.DEFAULT_BEERS_CSV, category_prices)

            history = core.load_history()
            historic_oz = core.historic_volume_by_beer(
                history, now, self.settings.rolling_volume_window_days)
            historic_category_oz = core.historic_volume_by_category(
                history, now, self.settings.rolling_category_window_days)

            purchases = core.allocate(
                beers, budget,
                historic_oz=historic_oz,
                historic_category_oz=historic_category_oz,
                settings=self.settings,
            )

            self._render_results(purchases, budget, beers, historic_oz, historic_category_oz)

            if self.save_to_history.get() and purchases:
                core.append_purchases_to_history(purchases, now)
                self._print(f"\nSaved {len(purchases)} purchase(s) to {core.HISTORY_FILE}")

        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _render_results(self, purchases, budget, beers, historic_oz, historic_category_oz):
        beer_by_name = {b.name: b for b in beers}
        spent = sum(p.price for p in purchases)

        self._print(f"Budget: ${budget:.2f}   Spent: ${spent:.2f}   Remaining: ${budget - spent:.2f}\n")

        totals = {}
        for p in purchases:
            category = beer_by_name[p.beer_name].category
            self._print(f"  {p.beer_name:22s} ({category:9s}) {p.size:2d}oz   ${p.price:.2f}")
            totals[p.beer_name] = totals.get(p.beer_name, 0) + p.size

        self._print("\nTotals per beer:")
        for name, oz in totals.items():
            self._print(f"  {name:22s} {oz}oz")

        if historic_oz:
            self._print(f"\n(Rolling {self.settings.rolling_volume_window_days}-day beer totals already on record:)")
            for name, oz in historic_oz.items():
                self._print(f"  {name:22s} {oz}oz")
        if historic_category_oz:
            self._print(f"\n(Rolling {self.settings.rolling_category_window_days}-day category totals already on record:)")
            for category, oz in historic_category_oz.items():
                self._print(f"  {category:22s} {oz}oz")


if __name__ == "__main__":
    try:
        core.ensure_default_files()

        root = tk.Tk()
        root.title("Beer Budget Optimizer - Settings")
        # Explicit on-screen position (not just size) - never leave this to
        # window-manager defaults.
        root.geometry("480x420+120+80")

        def launch_main_app(settings: core.Settings):
            for widget in root.winfo_children():
                widget.destroy()
            root.unbind("<Return>")

            root.title("Beer Budget Optimizer")
            root.geometry("720x600+120+80")

            app = BeerOptimizerApp(root, settings)

            # Open both editor windows, offset from root so they don't sit
            # exactly on top of the main window or each other.
            root.update_idletasks()
            beers_win = BeersEditor(root)
            beers_win.geometry(f"+{root.winfo_x() + 740}+{root.winfo_y()}")
            prices_win = CategoryPricesEditor(root)
            prices_win.geometry(f"+{root.winfo_x() + 740}+{root.winfo_y() + 440}")

        settings_frame = SettingsFrame(root, core.load_settings(), on_start=launch_main_app)
        settings_frame.pack(fill="both", expand=True)

        root.mainloop()

    except Exception:
        # Safety net: if something goes wrong before the window is up (e.g.
        # a corrupted data file slipping past the normal handling), this
        # writes the full error to a log file next to the program's data,
        # instead of failing silently with --windowed builds where there's
        # no console to see a traceback in.
        import traceback
        log_path = os.path.join(core.get_data_dir(), "error_log.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now().isoformat()} ---\n")
            traceback.print_exc(file=f)
        try:
            messagebox.showerror(
                "Beer Budget Optimizer - Error",
                f"Something went wrong on startup.\n\nDetails were saved to:\n{log_path}"
            )
        except Exception:
            pass  # if even Tkinter itself is broken, the log file is the fallback
