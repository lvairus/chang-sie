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

### Stray thoughts about paper/approach

Char's analysis of two meta-analytic datasets/domains (fish + hydropower or wetland restoration and groundwater levels) showed these problems:

* Even in a "clean" meta-analysis spreadsheet, we can't do a simple 1:1 mapping of the spreadsheet to a gold standard eval JSON.
* The reason is that often outcomes of interest (e.g. groundwater level or fish biomass) are indirectly calculated from the paper (e.g. authors infer or copy individual values and average them or calculate a regression), and the intermediate trace objects (the original reported metrics) are not stored anywhere even if the source is mentioned.
* Hypothetically, we could try to build those intermediate trace objects into a gold-standard JSON object for eval. But in some cases, this seems to be a very hard problem where you would need deep domain expertise or the original meta-analysis authors. This was especially true for the groundwater dataset. Upon reviewing 5 of the input studies, I could not understand nor reproduce their GWL difference level measurement. For the fish hydro meta-analysis, in some cases, the authors only used a subset of values in a table to estimate means, etc., and it also wasn't obvious why they did that.
* But, we can at least build a more shallow gold standard dataset from their meta-analyses:
```
paper
 ├── study[1..S]
 │    ├── site[1..L]
 │    ├── population[1..P]
 │    ├── intervention[1..I]
 │    ├── comparator[1..C]
 │    └── outcome[1..O] ### This may often not be possible to rebuild, but we could get outcome metadata
 │          ├── timepoint[1..T]
 │          ├── reported_statistics
 │          ├── evidence
 │          └── derived_statistics
 ```

 #### Process for adding a new meta-analysis

 1. Read the meta-analysis and identify its core question (e.g. "what is the impact of hydropower dams on fish abundance") and read the methods and results carefully.
 2. From the methods and results, ensure you have an understanding of what the authors sought to extract.
 3. Look at the extraction Excel file(s) and focal sheet(s) within those Excel file(s).
 4. Select a handful (2-5) of studies within the extraction file based on: completeness, which should include enumerating the source for outcome or other measures, and diversity (e.g. older vs younger papers, geography).
 5. For each study, walk across the columns for those row(s) and see if you can reproduce the measurements. If you can, great! Those are candidate columns for a benchmark eval. If you cannot, note down the failure mode. Is the failure mode due to (select all that apply):
    + inadequate data in paper --> meta-analysis authors contacted original study authors for unpublished data, etc.
    + complex and indecipherable decision --> as an educated layperson, are you unable to reproduce the outcome/measurement because it requires deep domain knowledge and/or some arbitrary data extraction procedure that is not written down somewhere in the main text method or SI docs?
    + lack of persisting intermediate data --> authors calculated averages or regression slopes from data that they hand extracted from individual or multiple figure(s) and table(s) and did not note the original values anywhere.
6. Based on this assessment, come up with your schema for the meta-analysis domain.