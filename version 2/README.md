# MATLAB Profiler Trace Analyzer (Version 2)

A Python desktop application using **tkinter** to analyze MATLAB profiler
trace data exported as `.mat` files. The tool indexes
`LOOPER_FN` occurrences across multiple profiler dump files, enables lazy
loading of specific iteration ranges, and provides filtering, search, and
codebase coverage analysis.

---

## Requirements

| Dependency | Purpose                          |
|------------|----------------------------------|
| Python 3.9+| Runtime (Anaconda recommended)   |
| tkinter    | Desktop GUI (bundled with Python)|
| scipy      | Reading MATLAB `.mat` files      |
| numpy      | Array handling                   |

### Install dependencies

```bash
pip install scipy numpy
```

Or with Anaconda/Spyder:

```bash
conda install scipy numpy
```

`tkinter` ships with standard Python and Anaconda distributions.  No other
external dependencies are required.

### Troubleshooting: If scipy fails to install

If `pip install scipy` does not work on your system (common on older Windows
setups or restricted environments), you can switch the ingest layer to use
**h5py** instead.  Save your `.mat` files with the `-v7.3` flag (already
shown in the MATLAB code below) and install h5py manually:

1. Go to <https://www.lfd.uci.edu/~gohlke/pythonlibs/> — this is Christoph
   Gohlke's unofficial Windows Python extension packages page, a
   long-standing trusted resource for pre-built Python packages.
2. Search for **h5py** on the page and download the `.whl` file that matches
   your:
   - **Python version** (e.g. `cp311` = Python 3.11)
   - **Architecture** (`win_amd64` for 64-bit Windows)
3. Install it from your Anaconda terminal:

   ```bash
   pip install path\to\downloaded\h5py-*.whl
   ```

4. Then install h5py's companion package if not already present:

   ```bash
   pip install numpy
   ```

Once h5py is installed, update the import in `indexer.py` to use h5py
instead of `scipy.io.loadmat` (see the repository's git history for the
original h5py-based implementation).

---

## How to Generate the .mat Files in MATLAB

### The `-history` flag

MATLAB's built-in profiler records which functions are called and how long
they take.  When started with the **`-history`** flag, the profiler also
records a **chronological function call trace** — a 2×N matrix called
`FunctionHistory` that logs every function entry and exit in order.

### MATLAB code

The following MATLAB script runs a workload in a loop, periodically saving
the profiler data to zero-padded `.mat` files:

```matlab
profile on -history

for i = 1:totalIterations

    myFunction();

    if mod(i, 100) == 0
        profile off
        p = profile('info');
        save(sprintf('profile_iter_%06d.mat', i), 'p', '-v7.3');
        profile on -history
    end

end
```

Each saved `.mat` file contains a struct **`p`** with (among other fields):

| Field              | Description                                              |
|--------------------|----------------------------------------------------------|
| `FunctionTable`    | One entry per unique function. Each entry has `FunctionName` (the function's display name) and `FileName` (full path to the `.m` file). |
| `FunctionHistory`  | A **2×N** matrix. **Row 1** is the event type: `0` = CALL, `1` = RETURN. **Row 2** is a 1-based index into `FunctionTable`. |

### What is `LOOPER_FN`?

A user-defined function named **`LOOPER_FN`** acts as a delimiter for each
loop iteration inside the profiled code.  Its CALL/RETURN events are
numbered sequentially across all `.mat` files (occurrence 1, 2, 3, … K),
providing a stable way to reference individual iterations.

### Built-in detection

Any function whose `FileName` does **not** fall under the user-specified
**codebase directory** is classified as a MATLAB built-in.  Built-in
functions can be toggled on or off in the UI.

---

## How to Run the Application

### Stage 1 — Build the index (command line)

```bash
cd "version 2"
python indexer.py /path/to/mat_files
```

This scans every `.mat` file, locates all `LOOPER_FN` occurrences, and
writes `looper_fn_index.json` alongside the `.mat` files.  A summary and
the first 20 resolved trace rows are printed to the console.

### Stage 2–4 — Launch the GUI

```bash
cd "version 2"
python app.py
```

---

## How to Use Each Feature

### Specifying directories

1. **`.mat` Directory** — click **Browse…** and select the folder that
   contains your zero-padded `.mat` files.
2. **Codebase Directory** — click **Browse…** and select the root folder of
   your MATLAB source code.  This is used to distinguish user code from
   MATLAB built-in functions.

### Analyzing a trace slice (Stage 2)

1. Enter a start occurrence **J** and end occurrence **K** for `LOOPER_FN`.
   **K must be greater than J.**
2. Click **Analyze**.
3. The application will:
   - Build (or load) the `LOOPER_FN` index.
   - Determine which `.mat` files contain occurrences J through K.
   - Load **only** those files (lazy loading).
   - Slice the trace from the CALL of occurrence J to the RETURN of
     occurrence K (inclusive).
   - Display the trace in the scrollable list below.

### Toggles (Stage 3)

Both toggles are **OFF** by default:

| Toggle                | Effect when ON                          |
|-----------------------|-----------------------------------------|
| **Show built-ins**    | Reveals functions whose file path is outside the codebase directory. |
| **Show RETURN events**| Reveals all RETURN events for all functions. |

Changing a toggle immediately re-filters the displayed list.

### Search (Stage 3)

1. Type a function name in the **Search** field and press Enter or click
   **Find**.
2. The search is **case-insensitive** and matches the **exact function
   name** only.
3. It operates on the **currently visible rows** (respecting active
   toggles).
4. The status bar shows: `Found N instances of [FUNCTION_NAME]`.
5. The list auto-scrolls to the first match.
6. Use **< Prev** and **Next >** to step through matches one at a time.

### Coverage analysis (Stage 4)

1. Click **Coverage** (only active after Analyze has been run).
2. If no codebase directory has been set, you will be prompted to select
   one.
3. A new window opens showing:
   - **Percentage** of `.m` files in the codebase that were called during
     the selected trace slice.
   - A **Called .m Files** tab listing every `.m` file that appears in the
     trace.
   - An **Uncalled .m Files** tab listing every `.m` file in the codebase
     that was *not* reached.
   - Built-in functions are excluded entirely from this view.
