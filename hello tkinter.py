import tkinter as tk

root = tk.Tk()
root.title("Tkinter Test")
root.geometry("300x150+150+150")
tk.Label(root, text="If you can see this,\nTkinter works on this PC.", font=("Arial", 12)).pack(expand=True)
tk.Button(root, text="Close", command=root.destroy).pack(pady=10)
root.mainloop()
