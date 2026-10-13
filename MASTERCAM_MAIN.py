import configparser
import tkinter as tk
from tkinter import filedialog, messagebox

from index_generator import create_index
from nc_commands import count_search_code, read_nc_lines
from preview_manager import get_index_preview, get_manuscript_preview
from project_settings import load_project_settings, save_project_settings
from setup_copy_generator import create_manuscript


def main():
    from tkinterdnd2 import DND_FILES, TkinterDnD

    root = TkinterDnD.Tk()
    root.title("Gcode Trim Tool")
    root.geometry("900x820")
    root.minsize(800, 560)
    root.resizable(True, True)

    file_var = tk.StringVar()
    customer_var = tk.StringVar()
    part_number_var = tk.StringVar()
    index_var = tk.BooleanVar(value=True)
    manuscript_var = tk.BooleanVar(value=True)
    index_m06_var = tk.StringVar(value="3")
    index_m01_before_var = tk.StringVar(value="0")
    index_m01_var = tk.StringVar(value="2")
    manuscript_m06_var = tk.StringVar(value="20")
    manuscript_m01_var = tk.StringVar(value="20")
    search_code_var = tk.StringVar(value="M01")
    search_count_var = tk.StringVar(value="")
    index_before_label_var = tk.StringVar()
    index_after_label_var = tk.StringVar()
    manuscript_around_label_var = tk.StringVar()
    preview_var = tk.StringVar(value="index")

    def selected_file():
        value = file_var.get().strip()
        if not value:
            raise ValueError("Please select a program file.")
        return value

    def notes_value():
        return notes_text.get("1.0", "end-1c")

    def load_project_information(file_path):
        try:
            settings = load_project_settings(file_path)
        except (OSError, ValueError, configparser.Error) as error:
            messagebox.showerror("Settings Error", str(error), parent=root)
            auto_preview()
            return

        customer_var.set(settings["customer"])
        part_number_var.set(settings["part_number"])
        notes_text.delete("1.0", tk.END)
        notes_text.insert("1.0", settings["notes"])
        auto_preview()

    def select_file(file_path):
        file_var.set(file_path)
        load_project_information(file_path)

    def browse_file():
        file_path = filedialog.askopenfilename(
            title="Select G-code Program",
            filetypes=[
                ("NC Files", "*.nc"),
                ("Text Files", "*.txt"),
                ("All Files", "*.*"),
            ],
            parent=root,
        )
        if file_path:
            select_file(file_path)

    def drop_file(event):
        files = root.tk.splitlist(event.data)
        if files:
            select_file(files[0])

    def nonnegative_integer(variable, label):
        try:
            value = int(variable.get())
        except ValueError as error:
            raise ValueError(f"{label} must be a whole number.") from error
        if value < 0:
            raise ValueError(f"{label} cannot be negative.")
        return value

    def update_preview():
        input_file = selected_file()
        if preview_var.get() == "index":
            content = get_index_preview(
                input_file,
                nonnegative_integer(index_m06_var, "Lines before first M06"),
                nonnegative_integer(index_m01_before_var, "Lines before each M01"),
                nonnegative_integer(index_m01_var, "Lines after each M01"),
                customer_var.get(),
                part_number_var.get(),
                notes_value(),
                search_code_var.get(),
            )
        else:
            content = get_manuscript_preview(
                input_file,
                nonnegative_integer(manuscript_m06_var, "Lines after first M06"),
                nonnegative_integer(manuscript_m01_var, "Lines around each M01"),
                search_code_var.get(),
            )
        preview_text.delete("1.0", tk.END)
        preview_text.insert(tk.END, content)
        preview_status_var.set("")

    def auto_preview(*_args):
        if not file_var.get().strip():
            preview_text.delete("1.0", tk.END)
            preview_status_var.set("Select a program file to preview.")
            search_count_var.set("")
            return
        try:
            update_preview()
        except Exception as error:
            preview_text.delete("1.0", tk.END)
            preview_status_var.set(f"Preview error: {error}")
        update_search_count()

    def update_search_count(*_args):
        if not file_var.get().strip():
            search_count_var.set("")
            return
        try:
            lines = read_nc_lines(file_var.get())
            count = count_search_code(lines, search_code_var.get())
        except (OSError, ValueError):
            search_count_var.set("")
            return
        code = search_code_var.get()
        found = "match" if count == 1 else "matches"
        search_count_var.set(f"{count} {code} {found} found")

    def update_search_labels(*_args):
        code = search_code_var.get()
        index_before_label_var.set(f"Lines Before Each {code}")
        index_after_label_var.set(f"Lines After Each {code}")
        manuscript_around_label_var.set(f"Lines Before/After {code}")

    def set_preview(mode):
        preview_var.set(mode)
        preview_index_label.config(
            fg="#00B050" if mode == "index" else "black"
        )
        preview_manuscript_label.config(
            fg="#00B050" if mode == "manuscript" else "black"
        )
        preview_arrow_label.config(text="<<----" if mode == "index" else "---->>")
        auto_preview()

    def generate():
        try:
            input_file = selected_file()
            if not index_var.get() and not manuscript_var.get():
                raise ValueError("Select at least one output type.")

            index_settings = ()
            if index_var.get():
                index_settings = (
                    nonnegative_integer(index_m06_var, "Lines before first M06"),
                    nonnegative_integer(
                        index_m01_before_var, "Lines before each M01"
                    ),
                    nonnegative_integer(index_m01_var, "Lines after each M01"),
                )
            manuscript_settings = ()
            if manuscript_var.get():
                manuscript_settings = (
                    nonnegative_integer(manuscript_m06_var, "Lines after first M06"),
                    nonnegative_integer(manuscript_m01_var, "Lines around each M01"),
                )
            save_project_settings(
                input_file,
                customer_var.get(),
                part_number_var.get(),
                notes_value(),
            )

            created_files = []
            if index_var.get():
                created_files.append(
                    str(
                        create_index(
                            input_file,
                            *index_settings,
                            customer_var.get(),
                            part_number_var.get(),
                            notes_value(),
                            search_code_var.get(),
                        )
                    )
                )
            if manuscript_var.get():
                created_files.append(
                    str(
                        create_manuscript(
                            input_file,
                            *manuscript_settings,
                            search_code_var.get(),
                        )
                    )
                )
            messagebox.showinfo(
                "Success",
                "Created:\n\n" + "\n".join(created_files),
                parent=root,
            )
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror("Generation Error", str(error), parent=root)
        except Exception as error:
            messagebox.showerror(
                "Generation Error",
                f"Unexpected error: {error}",
                parent=root,
            )

    root.columnconfigure(0, weight=1)

    tk.Label(
        root,
        text="Gcode Trim Tool",
        font=("Arial", 16, "bold"),
    ).pack(pady=(10, 0))

    file_frame = tk.LabelFrame(root, text="Program File")
    file_frame.pack(fill="x", padx=10, pady=10)
    file_entry = tk.Entry(file_frame, textvariable=file_var, width=90)
    file_entry.pack(side="left", padx=5, pady=10)
    file_entry.drop_target_register(DND_FILES)
    file_entry.dnd_bind("<<Drop>>", drop_file)
    tk.Button(file_frame, text="Browse", command=browse_file).pack(
        side="left", padx=5
    )

    header_frame = tk.LabelFrame(root, text="Index Header Information")
    header_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(header_frame, text="Customer", width=12, anchor="w").grid(
        row=0, column=0, sticky="w", padx=5, pady=3
    )
    tk.Entry(header_frame, textvariable=customer_var, width=107).grid(
        row=0, column=1, padx=5, pady=3, sticky="w"
    )
    tk.Label(header_frame, text="Part Number", width=12, anchor="w").grid(
        row=1, column=0, sticky="w", padx=5, pady=3
    )
    tk.Entry(header_frame, textvariable=part_number_var, width=107).grid(
        row=1, column=1, padx=5, pady=3, sticky="w"
    )
    tk.Button(
        header_frame,
        text="Clear Notes",
        command=lambda: notes_text.delete("1.0", tk.END),
        width=12,
    ).grid(row=2, column=0, sticky="nw", padx=5, pady=3)
    notes_text = tk.Text(header_frame, width=80, height=3)
    notes_text.grid(row=2, column=1, padx=5, pady=3, sticky="w")
    notes_text.bind("<KeyRelease>", auto_preview)

    search_frame = tk.LabelFrame(root, text="Search Settings")
    search_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(search_frame, text="Search For (after first M06)").grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    tk.OptionMenu(
        search_frame, search_code_var, "M01", "M06", "G28"
    ).grid(row=0, column=1, padx=5, sticky="w")
    tk.Label(
        search_frame,
        textvariable=search_count_var,
        fg="#00529B",
    ).grid(row=0, column=2, padx=15, sticky="w")

    index_frame = tk.LabelFrame(root, text="Index Settings")
    index_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(index_frame, text="Lines Before First M06").grid(
        row=0, column=0, padx=5, pady=5
    )
    tk.Spinbox(index_frame, from_=0, to=100, textvariable=index_m06_var, width=8).grid(
        row=0, column=1
    )
    tk.Label(index_frame, textvariable=index_before_label_var).grid(
        row=0, column=2, padx=15
    )
    tk.Spinbox(
        index_frame, from_=0, to=100, textvariable=index_m01_before_var, width=8
    ).grid(row=0, column=3)
    tk.Label(index_frame, textvariable=index_after_label_var).grid(
        row=0, column=4, padx=15
    )
    tk.Spinbox(index_frame, from_=0, to=100, textvariable=index_m01_var, width=8).grid(
        row=0, column=5
    )

    manuscript_frame = tk.LabelFrame(root, text="Manuscript Settings")
    manuscript_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(manuscript_frame, text="Lines After First M06").grid(
        row=0, column=0, padx=5, pady=5
    )
    tk.Spinbox(manuscript_frame, from_=0, to=500, textvariable=manuscript_m06_var, width=8).grid(
        row=0, column=1
    )
    tk.Label(manuscript_frame, textvariable=manuscript_around_label_var).grid(
        row=0, column=2, padx=15
    )
    tk.Spinbox(manuscript_frame, from_=0, to=500, textvariable=manuscript_m01_var, width=8).grid(
        row=0, column=3
    )

    options_frame = tk.LabelFrame(root, text="Output Options")
    options_frame.pack(fill="x", padx=10, pady=5)
    tk.Checkbutton(
        options_frame, text="Generate Index File", variable=index_var
    ).pack(anchor="w", padx=10)
    tk.Checkbutton(
        options_frame, text="Generate Manuscript", variable=manuscript_var
    ).pack(anchor="w", padx=10)

    preview_control_frame = tk.LabelFrame(root, text="Preview Controls")
    preview_control_frame.pack(fill="x", padx=10, pady=5)
    preview_index_label = tk.Label(
        preview_control_frame,
        text="INDEX",
        fg="#00B050",
        font=("Arial", 10, "bold"),
        cursor="hand2",
    )
    preview_index_label.pack(side="left", padx=(10, 3), pady=5)
    preview_arrow_label = tk.Label(
        preview_control_frame,
        text="<<----",
        font=("Arial", 10, "bold"),
        cursor="hand2",
    )
    preview_arrow_label.pack(side="left", padx=3, pady=5)
    preview_manuscript_label = tk.Label(
        preview_control_frame,
        text="MANUSCRIPT",
        fg="black",
        font=("Arial", 10, "bold"),
        cursor="hand2",
    )
    preview_manuscript_label.pack(side="left", padx=(3, 10), pady=5)
    preview_index_label.bind("<Button-1>", lambda _event: set_preview("index"))
    preview_manuscript_label.bind(
        "<Button-1>", lambda _event: set_preview("manuscript")
    )
    preview_arrow_label.bind(
        "<Button-1>",
        lambda _event: set_preview(
            "manuscript" if preview_var.get() == "index" else "index"
        ),
    )

    preview_frame = tk.LabelFrame(root, text="Preview")
    preview_frame.pack(fill="both", expand=True, padx=10, pady=5)
    preview_scrollbar = tk.Scrollbar(preview_frame)
    preview_scrollbar.pack(side="right", fill="y")
    preview_text = tk.Text(preview_frame, height=8, wrap="none")
    preview_text.pack(fill="both", expand=True)
    preview_scrollbar.config(command=preview_text.yview)
    preview_text.config(yscrollcommand=preview_scrollbar.set)
    preview_status_var = tk.StringVar(value="Select a program file to preview.")
    tk.Label(
        root,
        textvariable=preview_status_var,
        anchor="w",
        fg="#B00020",
    ).pack(fill="x", padx=12)
    tk.Button(
        root,
        text="Generate",
        font=("Arial", 12, "bold"),
        width=20,
        command=generate,
    ).pack(pady=10)

    for variable in (
        index_m06_var,
        index_m01_before_var,
        index_m01_var,
        manuscript_m06_var,
        manuscript_m01_var,
        customer_var,
        part_number_var,
    ):
        variable.trace_add("write", auto_preview)

    update_search_labels()
    search_code_var.trace_add("write", update_search_labels)
    search_code_var.trace_add("write", auto_preview)

    root.mainloop()


if __name__ == "__main__":
    main()
