from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "coral_small_v1"
# SCHEMA_VERSION = "coralsie_tuttle_small_v0.1"

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


class BibliographicMetadata(ProviderBase):
    source_file_path: str = Field(description="Input Markdown or PDF path supplied to the extractor.")
    ref_id: str = Field(description="Manually supplied RefID associated with this paper.", alias="RefID")
    title: str | None = Field(default=None, description="Paper title.")
    authors: list[str] = Field(default_factory=list, description="List of paper authors.", alias="Author(s)")
    year: NumericOrCode = Field(default=None, description="Publication year.")
    doi: str | None = Field(default=None, description="Digital object identifier, if reported.")


class StudyMetadata(ProviderBase):
    study_location: str | None = Field(
        default=None,
        alias="Study location",
        description="Specific location where the study took place, e.g., name of ocean, bay, reef, island, and country.",
    )
    study_site: StudySite | None = Field(
        default=None,
        alias="Study site",
        description="Categorical variable for whether study was in a field or laboratory.",
        examples=["field", "laboratory", "field and laboratory"],
    )
    study_type: StudyType | None = Field(
        default=None,
        alias="Study type",
        description="Categorical variable for manipulative or observational experiment.",
        examples=["manipulative", "observational", "manipulative and observational"],
    )
    event_latitude: str | None = Field(
        default=None,
        alias="Event latitude",
        description="If there was a single stressor event, as with dredging or mining, etc., the location in latitude.",
    )
    event_longitude: str | None = Field(
        default=None,
        alias="Event longitude",
        description="If there was a single stressor event, as with dredging or mining, etc., the location in longitude.",
    )


class CoralPopulation(ProviderBase):
    coral_age_class: AgeClass | None = Field(
        default=None,
        alias="Coral age class",
        description="Categorical variable describing the broad age class of the coral used in the focal reference.",
        examples=["gametes", "larva", "juvenile", "adult"],
    )
    current_genus_name: str | None = Field(default=None, alias="Current genus name", description="genus name of focal species")
    current_species_name: str | None = Field(default=None, alias="Current species name", description="species name of focal species, single word excluding any preceding genus name")
    colony_form: str | None = Field(
        default=None,
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
        ],
    )


class SedimentExposure(ProviderBase):
    sediment_composition: str | None = Field(
        default=None,
        alias="Sediment composition",
        description="Brief description of substrate type and size, if analyzed; note if sediment was dried.",
    )
    sediment_level: NumericOrCode = Field(
        default=None,
        alias="Sediment level",
        description="Numeric value describing the experimented/observed level of exposure to sediment; if a range is reported instead of a mean, report the midpoint of the range here.",
    )
    sediment_level_uom: str | None = Field(
        default=None,
        alias="Sediment level UoM",
        description="Unit of measurement corresponding to sediment level, most often mg/L or NTU for suspended sediment or mg/cm2/day for deposited sediment.",
    )
    sediment_level_mg_cm2_day: NumericOrCode = Field(
        default=None,
        alias="Sediment level converted to mg/cm2/day",
        description="Sediment level converted to mg/cm2/day; if already in this unit, repeat the sediment level here.",
    )
    sediment_n_for_computing_average: NumericOrCode = Field(
        default=None,
        alias="Sediment N for computing average",
        description="Sample size used for computing average of sediment level; if N is reported as a range, use the lower end and note the reported range in notes.",
    )
    sediment_n_uom: str | None = Field(
        default=None,
        alias="Sediment N UoM",
        description="Unit of measurement corresponding to sediment N.",
        examples=["sediment traps for deposited sediment"],
    )
    error: NumericOrCode = Field(
        default=None, 
        alias="Sediment upper error estimate",
        description="Estimate of error for reported sediment level."
    )
    error_type: str | None = Field(
        default=None,
        alias="Sediment level error type",
        description="Type of error for reported sediment level.",
        examples=["s.e.", "s.d.", "95% CI"],
    )
    notes: str | None = Field(
        default=None,
        alias="Sediment notes",
        description="Any commentary concerning sediment stressor, including figure, table, or text from which information was taken.",
    )


class BinaryResponses(ProviderBase):
    increased_mucus: BinaryValue | None = Field(
        default=None,
        alias="Increased mucus?",
        description="Binary variable for whether or not this condition/treatment/control found increased mucus production with respect to the control/ambient conditions.",
        examples=["0", "1"],
    )
    mortality_reported: BinaryValue | None = Field(
        default=None,
        alias="Mortality reported?",
        description="Whether the study reported binary data for mortality of any coral age class, partial or total, under specified condition/treatment.",
        examples=["0", "1"],
    )


class ResponseMeasurement(ProviderBase):
    response_type: str | None = Field(
        default=None,
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
        default=None, 
        alias="Response level",
        description="Numeric value describing coral's response to condition/treatment."
    )
    unit: str | None = Field(
        default=None, 
        alias="Unit of measurement",
        description="Unit of measurement corresponding to response level.")
    sample_size_n: NumericOrCode = Field(
        default=None,
        alias="N for computing average",
        description="Sample size used for computing average of response; if N is reported as a range, use the lower end and note the reported range in response_source.",
    )
    n_unit: str | None = Field(
        default=None,
        alias="N UoM",
        description="Unit of measurement corresponding to response N.",
        examples=["colonies", "fragments", "branches"],
    )
    response_source: str | None = Field(
        default=None,
        alias="Source of data",
        description="Figure, table, quote, or location in text from which these data were found, plus any other notes on this response.",
    )


class ExperimentalSetup(ProviderBase):
    study: StudyMetadata = Field(default_factory=StudyMetadata)
    population: CoralPopulation = Field(default_factory=CoralPopulation)
    exposure: SedimentExposure = Field(default_factory=SedimentExposure)
    binary_responses: BinaryResponses = Field(default_factory=BinaryResponses)
    responses: list[ResponseMeasurement] = Field(default_factory=list)


class PaperExtraction(ProviderBase):
    schema_version: str = Field(default=SCHEMA_VERSION, description="Schema version string for this CoralSIE extraction format.")
    bibliography: BibliographicMetadata
    num_setups: int | None = Field(
        default=None,
        ge=0,
        description="Number of setups recorded in the paper, where one setup is a unique set of coral genus and species, sediment composition, sediment level, and sediment exposure duration. This should be the length of the setups list.",
    )
    num_species: int | None = Field(
        default=None,
        ge=0,
        description="The number of different species (<genus> <species>) that are examined in this paper.",
    )
    num_responses: int | None = Field(
        default=None,
        ge=0,
        description="Number of response outcome types recorded in paper. This should be the length of the responses list in each setup. Each setup should have the same set of responses.",
    )
    setups: list[ExperimentalSetup] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="List of extraction warnings or uncertainty notes.")

    @model_validator(mode="after")
    def check_counts(self) -> "PaperExtraction":
        actual_setups = len(self.setups)
        response_counts = [len(setup.responses) for setup in self.setups]
        if self.num_setups is not None and self.num_setups != actual_setups:
            self.warnings.append(f"num_setups={self.num_setups} but extracted {actual_setups} setup objects")
        if self.num_responses is not None and response_counts and any(count != self.num_responses for count in response_counts):
            self.warnings.append(f"num_responses={self.num_responses} but setup response counts are {response_counts}")
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
