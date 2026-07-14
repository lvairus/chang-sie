from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "coral_v1"

EMPTY_SENTINELS = {"", "nan", "none", "null"}

AgeClass = Literal["gametes", "larva", "juvenile", "adult"]
BinaryValue = Literal["0", "1"]
StudySite = Literal["field", "laboratory", "field and laboratory"]
StudyType = Literal["manipulative", "observational", "manipulative and observational"]

NumericOrCode = float | str | None


def clean_empty(value: Any) -> Any:
    """Keep domain codes like n/r and n/a, but normalize truly empty values."""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in EMPTY_SENTINELS:
        return None
    return value


class ProviderBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("*", mode="before")
    @classmethod
    def empty_to_none(cls, value: Any) -> Any:
        return clean_empty(value)


class SourceEvidence(ProviderBase):
    source_quote: str | None = Field(
        default=None,
        description="Short quote or compact evidence span supporting this setup or response.",
    )
    source_page: NumericOrCode = Field(
        default=None,
        description="Page number where the supporting evidence appears, if available.",
    )
    source_table_or_figure: str | None = Field(
        default=None,
        description="Table, figure, appendix, or section identifier for the supporting evidence.",
    )


class BibliographicMetadata(ProviderBase):
    source_file_path: str = Field(description="Input Markdown or PDF path supplied to the extractor.")
    ref_id: str = Field(description="Manually supplied RefID associated with this paper.")
    title: str | None = Field(default=None, description="Paper title.")
    authors: list[str] = Field(default_factory=list, description="Paper authors.")
    year: NumericOrCode = Field(default=None, description="Publication year.")
    doi: str | None = Field(default=None, description="Digital object identifier, if reported.")


class StudyContext(ProviderBase):
    ocean: str | None = Field(default=None, description="ocean basin location where the study took place")
    study_location: str | None = Field(
        default=None,
        description="specific location where the study took place, e.g., name of bay, reef, island, and country",
    )
    study_site: StudySite | None = Field(
        default=None,
        description="categorical variable for whether study was in a field or laboratory",
        examples=["field", "laboratory", "field and laboratory"],
    )
    study_type: StudyType | None = Field(
        default=None,
        description="categorical variable for manipulative or observational experiment",
        examples=["manipulative", "observational", "manipulative and observational"],
    )
    event_latitude: NumericOrCode = Field(
        default=None,
        description="If there was a single stressor event, as with dredging or mining, etc., what was the location in latitude?",
    )
    event_longitude: NumericOrCode = Field(
        default=None,
        description="If there was a single stressor event, as with dredging or mining, etc., what was the location in longitude?",
    )


class CoralPopulation(ProviderBase):
    coral_age_class: AgeClass | None = Field(
        default=None,
        description="categorical variable describing the broad age class of the coral that was used in the focal reference; GAMETES - eggs and/or sperm, LARVA - pre-settlement or at settlement, JUVENILE - post-settlement, ADULT - older individuals not designated as juveniles in the text (most cases)",
        examples=["gametes", "larva", "juvenile", "adult"],
    )
    current_genus_name: str | None = Field(default=None, description="genus name of focal species")
    current_species_name: str | None = Field(default=None, description="species name of focal species, single word excluding any preceding genus name")
    colony_form: str | None = Field(
        default=None,
        description="categorical variable for the morphological form that the coral colony takes. Favor single word morphological descriptions",
        examples=[
            "massive",
            "palmate",
            "plating",
            "ramose",
            "branching",
            "submassive",
            "cup",
            "encrusting",
            "flabellate",
            "foliaceous",
            "free-living",
            "phaceloid",
        ],
    )


class SedimentExposure(ProviderBase):
    sediment_composition: str | None = Field(default=None, description="brief description of substrate type and size, if analyzed; note if sediment was dried")
    sediment_level: NumericOrCode = Field(default=None, description="numeric value describing the experimented/observed level of exposure to sediment; if a range (e.g., X - Y) is reported instead of a mean, then report the midpoint of the range here")
    sediment_level_uom: str | None = Field(default=None, description="unit of measurement (UoM) corresponding to sediment level (most often mg/L or NTU for suspended sediment or mg/cm2/d for deposited sediment)")
    sediment_level_mg_cm2_day: NumericOrCode = Field(
        default=None,
        description="sediment level converted to mg/cm2/day (if already in this UoM, then REPEAT the sediment level here)",
    )
    sediment_level_mg_l: NumericOrCode = Field(
        default=None,
        description="sediment level converted to mg/L (if already in this UoM, then REPEAT the sediment level here)",
    )
    sediment_level_average_type: str | None = Field(
        default=None,
        description="categorical variable for type of average reported for the sediment level; if range, see special instructions in note for \"Sediment level\"",
        examples=["absolute", "mean", "median", "mode", "range"],
    )
    sediment_n_for_computing_average: NumericOrCode = Field(
        default=None,
        description="sample size used for computing average of sediment level; if N is reported as a range instead of an exact sample size by treatment, then put the lower end of the range here and make a note of the reported range in the notes at the end of this section",
    )
    sediment_n_uom: str | None = Field(default=None, description="unit of measurement corresponding to sediment N", examples=["sediment traps for deposited sediment"])
    lower_error: NumericOrCode = Field(default=None, description="lower estimate of error for reported sediment level, e.g., if reported 0.7+/-0.1, then enter '0.1' here (NOT 0.6, the lower error 'bound'); if a range (e.g., X - Y) is reported instead of a mean, then the lower error estimate = 'sediment level' - X (where 'sediment level' is the midpoint of the reported range)")
    upper_error: NumericOrCode = Field(default=None, description="upper estimate of error for reported sediment level, e.g., if reported 0.7+/-0.1, then enter '0.1' here (NOT 0.8, the upper error 'bound'); if a range (e.g., X - Y) is reported instead of a mean, then the 'upper error estimate' = Y - 'sediment level' (where 'sediment level' is the midpoint of the reported range)")
    error_type: str | None = Field(default=None, description="type of error for reported sediment level; see QUICK KEY for abbreviations (\"s.e.\" for standard error of the mean, \"s.d.\" for standard deviation, \"95% CI\" for 95% confidence interval", examples=["s.e.", "s.d.", "95% CI"])
    exposure_duration: NumericOrCode = Field(default=None, description="numeric value of duration of time that coral was exposed to sediment level")
    duration_unit: str | None = Field(default=None, description="unit of measurement corresponding to exposure duration")
    duration_days: NumericOrCode = Field(
        default=None,
        description="numeric value of duration of time that coral was exposed to sediment level in # of days",
    )
    notes: str | None = Field(default=None, description="any commentary concerning sediment stressor, including Figure/Table/Text from which information was taken")


class BinaryResponses(ProviderBase):
    high_yield_chla: BinaryValue | None = Field(default=None, description="binary variable for whether or not this condition/treatment/control found increased yield or chlorophyll A content with respect to the control/ambient conditions; LEAVE BLANK if not reported or mentioned (do NOT write n/r, n/a), control is always \"0\" (no), and treatment is either \"0\" or \"1\" (yes)", examples=["0", "1"])
    reduced_p_r: BinaryValue | None = Field(default=None, description="binary variable for whether or not this condition/treatment/control found reduced photosynthesis/respiration ratios with respect to the control/ambient conditions", examples=["0", "1"])
    reduced_photosynthetic_efficiency: BinaryValue | None = Field(default=None,description="binary variable for whether or not this condition/treatment/control found reduced photosynthetic efficiency with respect to the control/ambient conditions", examples=["0", "1"])
    reduced_growth_rate: BinaryValue | None = Field(default=None, description="binary variable for whether or not this condition/treatment/control found reduced growth rate with respect to the control/ambient conditions", examples=["0", "1"])
    death_of_colonies: BinaryValue | None = Field(default=None, description="binary variable for whether or not this condition/treatment/control found death of whole colonies with respect to the control/ambient conditions", examples=["0", "1"])
    binary_response_source: str | None = Field(default=None, description="any notes on from where binary data were derived")


class DataReported(ProviderBase):
    non_adverse_effect_reported: BinaryValue | None = Field(default=None, description="binary variable specifying whether the study reported binary data for non-adverse effects of sediment on coral under specified condition/treatment", examples=["0", "1"])
    adverse_effect_reported: BinaryValue | None = Field(default=None, description="binary variable specifying whether the study reported binary data for adverse effects of sediment on coral under specified condition/treatment", examples=["0", "1"])
    mortality_reported: BinaryValue | None = Field(default=None, description="binary variable specifying whether the study reported binary data for mortality of any age class of coral (partial or total) under specified condition/treatment", examples=["0", "1"])
    adult_mortality_reported: BinaryValue | None = Field(default=None, description="binary variable specifying whether the study reported binary data for mortality of adult corals only (partial or total) under specified condition/treatment", examples=["0", "1"])


class ResponseMeasurement(ProviderBase):
    response_type: str | None = Field(
        default=None,
        description="categorical variable that broadly describes the type of measured response by the coral; suggested response types listed, but this list is not exhaustive -- you can write-in other response. Favor shorter type names (1-3 words on average) rather than longer descriptive strings.",
        examples=[
            "Bleaching",
            "Calcification rate",
            "Chlorophyll concentration",
            "Growth rate",
            "Mortality rate",
            "Mucus Production",
            "Photosynthesis",
            "Respiration",
        ],
    )
    level: NumericOrCode = Field(default=None, description="numeric value describing coral's response to condition/treatment")
    unit: str | None = Field(default=None, description="unit of measurement corresponding to response level")
    level_type: str | None = Field(default=None, description="categorical variable for type of average reported for the response", examples=["absolute/raw", "mean", "median", "mode", "range"])
    sample_size_n: NumericOrCode = Field(default=None, description="sample size used for computing average of response; if N is reported as a range instead of an exact sample size by treatment, then put the lower end of the range here and make a note of the reported range in the notes at the end of this section")
    n_unit: str | None = Field(default=None, description="unit of measurement corresponding to response N ", examples=["colonies", "fragments", "branches"])
    time_to_response_numeric: NumericOrCode = Field(default=None, description="numeric value indicating amount of time elapsed between start of stressor and start of response")
    time_to_response_uom: str | None = Field(default=None, description="unit of measurement corresponding to amount of time elapsed between start of stressor and start of response")
    response_source: str | None = Field(default=None, description="Figure, Table, or location in text from which these data were found in the the focal reference and any other notes on this response")
    evidence: SourceEvidence = Field(default_factory=SourceEvidence)


class ExperimentalSetup(ProviderBase):
    population: CoralPopulation = Field(default_factory=CoralPopulation)
    exposure: SedimentExposure = Field(default_factory=SedimentExposure)
    binary_responses: BinaryResponses = Field(default_factory=BinaryResponses)
    data_reported: DataReported = Field(default_factory=DataReported)
    responses: list[ResponseMeasurement] = Field(default_factory=list)
    evidence: SourceEvidence = Field(default_factory=SourceEvidence)


class PaperExtraction(ProviderBase):
    schema_version: str = Field(default=SCHEMA_VERSION)
    bibliography: BibliographicMetadata
    ocean: str | None = Field(default=None, description="ocean basin location where the study took place")
    study_location: str | None = Field(
        default=None,
        description="specific location where the study took place, e.g., name of bay, reef, island, and country",
    )
    study_site: StudySite | None = Field(
        default=None,
        description="categorical variable for whether study was in a field or laboratory",
        examples=["field", "laboratory", "field and laboratory"],
    )
    study_type: StudyType | None = Field(
        default=None,
        description="categorical variable for manipulative or observational experiment",
        examples=["manipulative", "observational", "manipulative and observational"],
    )
    event_latitude: NumericOrCode = Field(
        default=None,
        description="If there was a single stressor event, as with dredging or mining, etc., what was the location in latitude? If there was no single stressor event, write n/a.",
    )
    event_longitude: NumericOrCode = Field(
        default=None,
        description="If there was a single stressor event, as with dredging or mining, etc., what was the location in longitude? If there was no single stressor event, write n/a.",
    )
    num_setups: int | None = Field(
        default=None,
        ge=0,
        description="number of setups recorded in paper, where one setup is a unique set of coral genus and species, sediment composition, sediment level, and sediment exposure duration. This should be the length of the \"setups\" list",
    )
    num_species: int | None = Field(
        default=None,
        ge=0,
        description="Number of different species (<genus> <species>) examined in this paper.",
    )
    num_responses: int | None = Field(
        default=None,
        ge=0,
        description="number of response outcome types recorded in paper. This should be the length of the \"responses\" list in each setup. Each setup should have the same set of responses.",
    )
    setups: list[ExperimentalSetup] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_counts(self) -> "PaperExtraction":
        actual_setups = len(self.setups)
        actual_responses = sum(len(setup.responses) for setup in self.setups)
        if self.num_setups is not None and self.num_setups != actual_setups:
            self.warnings.append(f"num_setups={self.num_setups} but extracted {actual_setups} setup objects")
        if self.num_responses is not None and self.num_responses != actual_responses:
            self.warnings.append(f"num_responses={self.num_responses} but extracted {actual_responses} response objects")
        if not self.setups and "no setups extracted" not in self.warnings:
            self.warnings.append("no setups extracted")
        return self


class ProviderResponse(ProviderBase):
    parsed_payload: PaperExtraction | dict[str, Any] | None = None
    raw_response: str | dict[str, Any] | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    model_name: str | None = None
    provider_name: str | None = None
    prompt_version: str | None = None
    cost_metadata: dict[str, Any] = Field(default_factory=dict)
