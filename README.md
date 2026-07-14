# Benchmarking Environmental SIE

This repo contain the code for benchmarking LLM performance on structured information extraction to reproduce meta-anlyses ground truth datasets.

The code is currently specifically for the Coral meta-analysis from: Tuttle, L.J., Donahue, M.J. Effects of sediment exposure on corals: a systematic review of experimental studies. Environ Evid 11, 4 (2022). https://doi.org/10.1186/s13750-022-00256-0


File System:
- `data`
    - `md_to_id_map.csv`: mapping of markdown filenames to their IDs in the ground truth. The pipeline runs all the papers in this file.
    - `truth_papers.csv`: ground truth for paper-level data extraction
    - `truth_responses.csv`: ground truth for response-level data extraction
    - `truth_setups.csv`: ground truth for setup-level data extraction
(each paper creates a row in truth_papers.csv, each paper has a list of setups that are in truth_setups.csv, and each setup has a list of responses that are in truth_responses.csv)
    - `tuttle.xlsx`: original spreadsheet of meta analysis dataset, downloaded from Tuttle and Donahue paper
    - `tuttle2022.csv`: cleaned csv of original spreadsheet (removed some columns that wouldn't be extracted)
    - `var_task_types.csv`: table of variables and their different types (numerical vs categorical, original vs inferred, etc)
    - `vars_to_extract.csv`: table of variables, their descriptions, and examples, used to help create the schema
- `mds`: folder of markdown files, omitted for copyright reasons 
- `outputs`: folder where all extraction results are recorded
- `pdfs`: folder of pdf files, ommited for copyright reasons
- `config.json`: configuration file to run extraction, evaluation, and performance plotting
- `eval.py`: evaluation script
- `extract.py`: extraction script
- `normalize_truth.py`: script used to normalize ground truth spreadsheet (`tuttle2022.csv`) into separate tables (`truth_papers.csv`, `truth_setups.csv`, `truth_responses.csv`)
- `pdf_to_md.py`: script to convert pdf files to markdown
- `plot_performance.py`: performance plotting script
- `prompt.py`: script for defining system and user prompt to LLM
- `run_pipeline.py`: script to run extraction, evaluation, and performance plotting scripts with one call
- `schema-summary-small.json`: human-readable schema, small version
- `schema-summary.json`: human-readable schema, original version
- `schema-small-req.py`: script defining schema, small version with all fields required
- `schema-small.py`: script defining schema, small version with all fields required
- `schema.py`: script defining schema, original version

How to Use:
- upload pdf files (from Coral dataset) into `pdfs` folder
- run `python3 pdf_to_md.py` to convert pdfs into mds, saved in `mds` folder
- make sure the md files and their corresponding IDs are in `md_to_id_map.csv` for the pipeline to process them
- set configuration in config.json: 
    - `run_name`: name of output folder containing all results (saved in `outputs` folder)
    - `model`: choice of LLM to use for extraction. possible choices:
        - meta-llama/llama-3.1-8b-instruct 
        - meta-llama/llama-3.1-70b-instruct
        - deepseek/deepseek-v4-pro
        - openai/gpt-5.4-nano
    - `limit`: if you'd like to test with just one paper, set `limit` to 1 and the pipeline will stop after processing 1 paper. if not, leave `limit` as `null`.
- set up your Open Router api key at https://openrouter.ai/ then setting it in the command line with `OPENROUTER_API_KEY="your api key"`
- once everything is set up, run `python3 run_pipeline.py`
- your results will be in `outputs/<run_name>`

Results:

- `run_logs`: folder with any error logs
- `run_info.json`: information on the run such as name, LLM type, schema type, number of successful papers, etc
- `extractions_info.csv`: information on each extracted paper, such as filename, model, success status, duration of extraction, token usage, etc
- `extractions.jsonl`: jsonl object returned from LLM, normalized into the 3 csvs below
- `paper_info.csv`: paper-level extracted data
- `setups.csv`: setup-level extracted data
- `responses.csv`: response-level extracted data
- `eval`: folder with evaluation and row-matching results
    - `plots`: folder with plotted graphs to visualize performance
