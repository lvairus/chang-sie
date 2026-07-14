from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "coral_small_required_v1"
# SCHEMA_VERSION = "coralsie_tuttle_small_required_v0.1"

EMPTY_SENTINELS = {"", "nan", "none", "null"}

AgeClass = Literal["gametes", "larva", "juvenile", "adult", "n/r", "n/a"]
BinaryValue = Literal["0", "1", "n/r", "n/a"]
StudySite = Literal["field", "laboratory", "field and laboratory", "n/r", "n/a"]
StudyType = Literal["manipulative", "observational", "manipulative and observational", "n/r", "n/a"]

NumericOrCode = float | str


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


class BibliographicMetadata(ProviderBase):
    source_file_path: str = Field(description="Input Markdown or PDF path supplied to the extractor.")
    ref_id: str | None = Field(default=None, description="Manually supplied RefID associated with this paper.", alias="RefID")
    title: str = Field(description="Paper title.")
    authors: list[str] = Field(description="List of paper authors.", alias="Author(s)")
    year: NumericOrCode = Field(description="Publication year.")
    doi: str = Field(description="Digital object identifier, if reported.")


class StudyMetadata(ProviderBase):
    study_location: str = Field(
        alias="Study location",
        description="Specific location where the study took place, e.g., name of ocean, bay, reef, island, and country.",
    )
    study_site: StudySite = Field(
        alias="Study site",
        description="Categorical variable for whether study was in a field or laboratory.",
        examples=["field", "laboratory", "field and laboratory", "n/r", "n/a"],
    )
    study_type: StudyType = Field(
        alias="Study type",
        description="Categorical variable for manipulative or observational experiment.",
        examples=["manipulative", "observational", "manipulative and observational", "n/r", "n/a"],
    )
    event_latitude: str = Field(
        alias="Event latitude",
        description="If there was a single stressor event, as with dredging or mining, etc., the location in latitude.",
    )
    event_longitude: str = Field(
        alias="Event longitude",
        description="If there was a single stressor event, as with dredging or mining, etc., the location in longitude.",
    )


class CoralPopulation(ProviderBase):
    coral_age_class: AgeClass = Field(
        alias="Coral age class",
        description="Categorical variable describing the broad age class of the coral used in the focal reference.",
        examples=["gametes", "larva", "juvenile", "adult", "n/r", "n/a"],
    )
    current_genus_name: str = Field(alias="Current genus name", description="Genus name of focal species.")
    current_species_name: str = Field(alias="Current species name", description="Species name of focal species, single word excluding any preceding genus name.")
    colony_form: str = Field(
        alias="Colony form",
        description="Categorical variable for the morphological form that the coral colony takes.",
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
            "n/r",
            "n/a",
        ],
    )


class SedimentExposure(ProviderBase):
    sediment_composition: str = Field(
        alias="Sediment composition",
        description="Brief description of substrate type and size, if analyzed; note if sediment was dried.",
    )
    sediment_level: NumericOrCode = Field(
        alias="Sediment level",
        description="Numeric value describing the experimented/observed level of exposure to sediment; report just a number, without units and without non-numeric characters. if a range is reported instead of a mean, report the midpoint of the range here.",
    )
    sediment_level_uom: str = Field(
        alias="Sediment level UoM",
        description="Unit of measurement corresponding to sediment level, most often mg/L or NTU for suspended sediment or mg/cm2/day for deposited sediment.",
    )
    sediment_level_mg_cm2_day: NumericOrCode = Field(
        alias="Sediment level converted to mg/cm2/day",
        description="Sediment level converted to mg/cm2/day; if already in this unit, repeat the sediment level here.",
    )
    sediment_n_for_computing_average: NumericOrCode = Field(
        alias="Sediment N for computing average",
        description="Sample size used for computing average of sediment level; if N is reported as a range, use the lower end and note the reported range in notes.",
    )
    sediment_n_uom: str = Field(
        alias="Sediment N UoM",
        description="Unit of measurement corresponding to sediment N.",
        examples=["sediment traps for deposited sediment", "n/r", "n/a"],
    )
    error: NumericOrCode = Field(
        alias="Sediment upper error estimate",
        description="Estimate of error for reported sediment level.",
    )
    error_type: str = Field(
        alias="Sediment level error type",
        description="Type of error for reported sediment level.",
        examples=["s.e.", "s.d.", "95% CI", "n/r", "n/a"],
    )
    notes: str = Field(
        alias="Sediment notes",
        description="Any commentary concerning sediment stressor, including figure, table, or text from which information was taken.",
    )


class BinaryResponses(ProviderBase):
    increased_mucus: BinaryValue = Field(
        alias="Increased mucus?",
        description="Binary variable for whether or not this condition/treatment/control found increased mucus production with respect to the control/ambient conditions.",
        examples=["0", "1", "n/r", "n/a"],
    )
    mortality_reported: BinaryValue = Field(
        alias="Mortality reported?",
        description="Whether the study reported binary data for mortality of any coral age class, partial or total, under specified condition/treatment.",
        examples=["0", "1", "n/r", "n/a"],
    )


class ResponseMeasurement(ProviderBase):
    response_type: str = Field(
        alias="Response type",
        description="Short categorical variable that broadly describes the measured coral response. Different response types within a set must have unique values.",
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
    level: NumericOrCode = Field(
        alias="Response level",
        description="Numeric value describing coral's response to condition/treatment.",
    )
    unit: str = Field(
        alias="Unit of measurement",
        description="Unit of measurement corresponding to response level.",
    )
    sample_size_n: NumericOrCode = Field(
        alias="N for computing average",
        description="Sample size used for computing average of response; if N is reported as a range, use the lower end and note the reported range in response_source.",
    )
    n_unit: str = Field(
        alias="N UoM",
        description="Unit of measurement corresponding to response N.",
        examples=["colonies", "fragments", "branches", "n/r", "n/a"],
    )
    response_source: str = Field(
        alias="Source of data",
        description="Figure, table, quote, or location in text from which these data were found, plus any other notes on this response.",
    )


class ExperimentalSetup(ProviderBase):
    study: StudyMetadata = Field(description="Study metadata associated with this setup.")
    population: CoralPopulation = Field(description="Coral population associated with this setup.")
    exposure: SedimentExposure = Field(description="Sediment exposure associated with this setup.")
    binary_responses: BinaryResponses = Field(description="Binary response indicators associated with this setup.")
    responses: list[ResponseMeasurement] = Field(description="Measured coral responses associated with this setup.")


class PaperExtraction(ProviderBase):
    schema_version: str = Field(description="Schema version string for this CoralSIE extraction format.")
    bibliography: BibliographicMetadata
    num_setups: int = Field(
        ge=0,
        description="Number of setups recorded in the paper, where one setup is a unique set of coral genus and species, sediment composition, sediment level, and sediment exposure duration. This should be the length of the setups list.",
    )
    num_species: int = Field(
        ge=0,
        description="The number of different species (<genus> <species>) that are examined in this paper.",
    )
    num_responses: int = Field(
        ge=0,
        description="Number of response outcome types recorded in paper. This should be the length of the responses list in each setup. Each setup should have the same set of responses.",
    )
    setups: list[ExperimentalSetup] = Field(description="Extracted setup objects.")
    warnings: list[str] = Field(description="List of extraction warnings or uncertainty notes.")

    @model_validator(mode="after")
    def check_counts(self) -> "PaperExtraction":
        actual_setups = len(self.setups)
        response_counts = [len(setup.responses) for setup in self.setups]
        if self.num_setups != actual_setups:
            self.warnings.append(f"num_setups={self.num_setups} but extracted {actual_setups} setup objects")
        if response_counts and any(count != self.num_responses for count in response_counts):
            self.warnings.append(f"num_responses={self.num_responses} but setup response counts are {response_counts}")
        if not self.setups and "no setups extracted" not in self.warnings:
            self.warnings.append("no setups extracted")
        return self


class ProviderResponse(ProviderBase):
    parsed_payload: PaperExtraction | dict[str, Any] = Field(description="Parsed extraction payload, if available.")
    raw_response: str | dict[str, Any] = Field(description="Raw provider response, if available.")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model_name: str = Field(description="Model name used for extraction.")
    provider_name: str = Field(description="Provider name used for extraction.")
    prompt_version: str = Field(description="Prompt version used for extraction.")
    cost_metadata: dict[str, Any] = Field(description="Provider cost metadata.")
