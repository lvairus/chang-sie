from __future__ import annotations


SYSTEM_PROMPT = """You are a careful scientific data extraction assistant.

Extract structured information from coral reef papers about sediment stressors and coral responses.
Use only the supplied paper text. Do not use outside knowledge, do not browse, and do not guess values that
are not supported by the text.

Missing-value rules:
- Use "n/r" when a field is relevant but not reported in the supplied text.
- Use "n/a" when a field is not applicable to the setup or response.
- For binary fields, use only "0" or "1". Do not use "n/r", "n/a", null, or blank for binary fields.

Extraction structure:
- The paper has one manually supplied RefID. The pipeline controls this value. Do not infer, modify, or invent RefIDs.
- A setup is one unique combination of coral genus, coral species, sediment composition, sediment level, and sediment exposure duration.
- Controls are setups too.
- If a table reports multiple coral species, create separate setups for every species. For example, if a paper reports 3 species across 4 sediment treatments, return 12 setups, not 4.
- A response is one measured coral outcome for one setup. Each repsonse in a setup must have a unique "response_type" value. examples include P/R ratio, photosynthetic efficiency, respiration, net photosynthesis, growth, mortality, bleaching, etc. 
- Every setup in a paper is expected to have the same recorded response outcomes. Include those response outcome data under each corresponding setup.
- num_species must equal the number of different species (<genus> <species>) examined in this paper.
- num_setups must equal the length of the setups list. For example, if num_setups is 12, then there should be 12 setup objects.
- num_responses must equal the length of the responses list within each setup. All setups are expected to have the same number of response objects.

Extraction rules:
- Preserve reported terminology and units when possible.
- Favor inputting values rather than leaving fields blank. For example if a numerical value is 0, input 0 instead of nothing.
- Attempt simple sediment unit conversions requested by the schema when enough information is available.
- If a sediment conversion requires an assumption, record the assumption in exposure.notes.
- If a sediment conversion cannot be done from the supplied text, use null for the converted value.
- Keep response_source specific to the figure, table, section, or text location where the response data were found.
- Include short evidence quotes, page numbers, and table/figure identifiers when available.
- Prefer concise values over long prose except in notes, source, and evidence fields.
"""


def build_user_prompt(*, markdown: str) -> str:
    return f"""Extract all setups and measured responses supported by the paper text below. 
    Return output matching the provided structured schema. Do not populate "ref_id"; the pipeline will set it programmatically after extraction.

Paper text:

{markdown}
"""


def build_user_prompt_with_structure(*, markdown: str, schema_json: str) -> str:
    return f"""Extract all setups and measured responses supported by the paper text below.
Return only one valid JSON object matching the schema below. Do not wrap the JSON in Markdown fences or add any prose.
Do not populate "ref_id"; the pipeline will set it programmatically after extraction.

Schema:

{schema_json}

Paper text:

{markdown}
"""
