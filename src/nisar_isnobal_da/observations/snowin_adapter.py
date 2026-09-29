"""Adapt already processed SnowIn xarray output to the project boundary.

This module validates and labels existing values. It does not read NISAR
products, calculate dSWE, alter phase, reference observations, or estimate
uncertainty.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from numbers import Real
from typing import Any

import numpy as np
import xarray as xr

_CANONICAL_PHASE = "secondary_minus_reference"
_SOURCE_PHASES = {"reference_minus_secondary", _CANONICAL_PHASE}
_PHASE_TRANSFORMS = {"identity", "multiply_by_-1"}
_DA_REQUIRED_FIELDS = {
    "dswe",
    "dswe_uncertainty",
    "observation_support",
    "pair_common_uncertainty",
    "local_uncertainty",
}


class SnowInObservationError(ValueError):
    """Raised when a SnowIn result violates the project observation contract."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SnowInObservationError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise SnowInObservationError(f"{field} must not contain surrounding whitespace")
    return value


def _utc_timestamp(value: Any, field: str) -> str:
    timestamp = _text(value, field)
    if not (timestamp.endswith("Z") or timestamp.endswith("+00:00")):
        raise SnowInObservationError(f"{field} must be an ISO 8601 UTC string")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnowInObservationError(
            f"{field} must be a valid ISO 8601 UTC string"
        ) from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise SnowInObservationError(f"{field} must be in UTC")
    return timestamp


def _require_pair_grid(pair: xr.Dataset, dswe: xr.DataArray) -> None:
    if dswe.dims != ("y", "x"):
        raise SnowInObservationError("dswe dimensions must be ('y', 'x')")
    for coordinate in ("y", "x"):
        if coordinate not in pair.coords or pair[coordinate].dims != (coordinate,):
            raise SnowInObservationError(
                f"SnowIn pair must contain a one-dimensional {coordinate!r} coordinate"
            )
        _text(pair[coordinate].attrs.get("units"), f"{coordinate} coordinate units")
        if pair.sizes[coordinate] != dswe.sizes[coordinate]:
            raise SnowInObservationError(
                f"dswe is not aligned with the pair's {coordinate!r} coordinate"
            )

    if "spatial_ref" not in pair.variables or pair["spatial_ref"].ndim != 0:
        raise SnowInObservationError(
            "SnowIn pair must include scalar spatial_ref CRS metadata"
        )
    crs_attrs = pair["spatial_ref"].attrs
    if not any(crs_attrs.get(key) for key in ("crs_wkt", "spatial_ref", "epsg_code")):
        raise SnowInObservationError(
            "spatial_ref must declare CRS metadata (crs_wkt, spatial_ref, or epsg_code)"
        )
    if dswe.attrs.get("grid_mapping") != "spatial_ref":
        raise SnowInObservationError("dswe must declare grid_mapping='spatial_ref'")


def _require_alignment(pair: xr.Dataset, name: str, reference: xr.DataArray) -> None:
    """Check index alignment without loading the variable's data values."""
    variable = pair[name]
    if variable.dims != reference.dims:
        raise SnowInObservationError(f"{name} dimensions must match dswe")
    try:
        xr.align(reference, variable, join="exact", copy=False)
    except ValueError as exc:
        raise SnowInObservationError(f"{name} coordinates must match dswe") from exc


def _boolean_support(pair: xr.Dataset, name: str) -> xr.DataArray:
    """Read boolean support, including its explicit NetCDF flag encoding."""
    variable = pair[name]
    if variable.dtype.kind == "b":
        return variable

    flag_values = np.asarray(variable.attrs.get("flag_values", [])).tolist()
    if (
        variable.dtype.kind in "iu"
        and flag_values == [0, 1]
        and variable.attrs.get("flag_meanings") == "unsupported supported"
        and np.isin(np.asarray(variable.data), [0, 1]).all()
    ):
        return variable.astype(bool)

    raise SnowInObservationError(
        f"{name} must be boolean or an explicitly encoded 0/1 support flag"
    )


def adapt_snowin_observation(
    pair: xr.Dataset,
    *,
    processing_maturity: str,
    processing_crid: str,
    processing_product_version: str,
    processing_collection_version: str,
    reference_method: str | None = None,
) -> xr.Dataset:
    """Return a shallow, provenance-enriched project observation Dataset.

    ``pair`` must already contain SnowIn's pair metadata and a ``dswe``
    DataArray. Processing identity is supplied from the catalog record so
    maturity, CRID, product version, and collection version remain distinct.
    No scientific values are changed or calculated. Missing uncertainty or
    support layers remain absent; use :func:`validate_da_observation` to check
    whether the result meets the complete DA observation contract.
    """
    if not isinstance(pair, xr.Dataset):
        raise TypeError("pair must be an xarray.Dataset")
    if "dswe" not in pair.data_vars:
        raise SnowInObservationError("pair must contain a dswe data variable")

    dswe = pair["dswe"]
    _require_pair_grid(pair, dswe)

    required_attrs = {
        "snowin_schema_version": None,
        "product_kind": "pairwise_interferogram",
        "temporal_edge": "reference_to_secondary",
        "phase_difference_definition": _CANONICAL_PHASE,
    }
    for name, expected in required_attrs.items():
        value = _text(pair.attrs.get(name), f"dataset attribute {name}")
        if expected is not None and value != expected:
            raise SnowInObservationError(
                f"dataset attribute {name} must be {expected!r}"
            )

    _utc_timestamp(pair.attrs.get("reference_time"), "reference_time")
    _utc_timestamp(pair.attrs.get("secondary_time"), "secondary_time")
    source_phase = _text(
        pair.attrs.get("source_phase_difference_definition"),
        "source_phase_difference_definition",
    )
    transform = _text(pair.attrs.get("phase_transform"), "phase_transform")
    if source_phase not in _SOURCE_PHASES:
        raise SnowInObservationError(
            "source_phase_difference_definition is not a recognized SnowIn convention"
        )
    if transform not in _PHASE_TRANSFORMS:
        raise SnowInObservationError("phase_transform must be explicit and recognized")
    expected_transform = (
        "multiply_by_-1" if source_phase == "reference_minus_secondary" else "identity"
    )
    if transform != expected_transform:
        raise SnowInObservationError(
            "phase_transform does not match the declared source phase convention"
        )

    wavelength = pair.attrs.get("wavelength_m")
    if isinstance(wavelength, bool) or not isinstance(wavelength, Real):
        raise SnowInObservationError("wavelength_m must be an explicit positive number")
    if not isfinite(wavelength) or wavelength <= 0:
        raise SnowInObservationError("wavelength_m must be an explicit positive number")

    if dswe.attrs.get("quantity") != "pairwise_dSWE":
        raise SnowInObservationError("dswe quantity must be 'pairwise_dSWE'")
    if dswe.attrs.get("units") != "m":
        raise SnowInObservationError("dswe units must be explicitly declared as 'm'")
    if dswe.attrs.get("phase_difference_definition") != _CANONICAL_PHASE:
        raise SnowInObservationError("dswe must declare the canonical phase direction")
    dswe_wavelength = dswe.attrs.get("wavelength_m")
    if (
        isinstance(dswe_wavelength, bool)
        or not isinstance(dswe_wavelength, Real)
        or not isfinite(dswe_wavelength)
        or dswe_wavelength != wavelength
    ):
        raise SnowInObservationError(
            "dswe wavelength_m must match the pair's explicit wavelength_m"
        )
    retrieval_method = _text(dswe.attrs.get("retrieval_method"), "retrieval_method")
    source_granule_id = _text(pair.attrs.get("source_granule_id"), "source_granule_id")
    recorded_reference_methods = {
        value
        for value in (
            pair.attrs.get("phase_reference_method"),
            dswe.attrs.get("phase_reference_method"),
        )
        if value is not None
    }
    if len(recorded_reference_methods) > 1:
        raise SnowInObservationError(
            "SnowIn Dataset and dswe reference methods disagree"
        )
    recorded_reference_method = next(iter(recorded_reference_methods), None)
    selected_reference_method = (
        reference_method if reference_method is not None else recorded_reference_method
    )
    selected_reference_method = _text(selected_reference_method, "reference_method")
    if selected_reference_method == "unknown":
        raise SnowInObservationError("reference_method must be explicit, not 'unknown'")
    if (
        recorded_reference_method is not None
        and selected_reference_method != recorded_reference_method
    ):
        raise SnowInObservationError(
            "explicit reference_method disagrees with SnowIn provenance"
        )

    processing = {
        "processing_maturity": processing_maturity,
        "processing_crid": processing_crid,
        "processing_product_version": processing_product_version,
        "processing_collection_version": processing_collection_version,
    }
    for name, value in processing.items():
        processing[name] = _text(value, name)

    result = pair.copy(deep=False)
    result.attrs = dict(pair.attrs)
    result.attrs.update(
        {
            **processing,
            "source_granule_id": source_granule_id,
            "retrieval_method": retrieval_method,
            "reference_method": selected_reference_method,
        }
    )

    if "pairwise_supported" in pair and "observation_support" not in pair:
        _require_alignment(pair, "pairwise_supported", dswe)
        result["observation_support"] = _boolean_support(pair, "pairwise_supported")
    if "observation_support" in pair:
        _require_alignment(pair, "observation_support", dswe)
        result["observation_support"] = _boolean_support(pair, "observation_support")

    return result


def validate_da_observation(observation: xr.Dataset) -> None:
    """Raise when an observation lacks any charter-required DA field.

    The validator does not create support or uncertainty values. It returns
    ``None`` only when the observation carries the fields required by charter
    §11 and the explicit processing identity required by the data policy.
    """
    if not isinstance(observation, xr.Dataset):
        raise TypeError("observation must be an xarray.Dataset")

    missing = sorted(_DA_REQUIRED_FIELDS.difference(observation.data_vars))
    required_attrs = {
        "temporal_edge",
        "phase_difference_definition",
        "reference_time",
        "secondary_time",
        "source_granule_id",
        "processing_maturity",
        "processing_crid",
        "processing_product_version",
        "processing_collection_version",
        "retrieval_method",
        "reference_method",
    }
    missing.extend(
        f"attribute:{name}"
        for name in sorted(required_attrs)
        if not observation.attrs.get(name)
    )
    if missing:
        raise SnowInObservationError(
            "DA observation is incomplete; missing " + ", ".join(missing)
        )

    if observation.attrs["temporal_edge"] != "reference_to_secondary":
        raise SnowInObservationError("temporal_edge must be 'reference_to_secondary'")
    if observation.attrs["phase_difference_definition"] != _CANONICAL_PHASE:
        raise SnowInObservationError(
            "phase_difference_definition must be 'secondary_minus_reference'"
        )
    _utc_timestamp(observation.attrs["reference_time"], "reference_time")
    _utc_timestamp(observation.attrs["secondary_time"], "secondary_time")

    dswe = observation["dswe"]
    _require_pair_grid(observation, dswe)
    if dswe.attrs.get("quantity") != "pairwise_dSWE" or dswe.attrs.get("units") != "m":
        raise SnowInObservationError("dswe must be pairwise_dSWE with units 'm'")
    if dswe.attrs.get("phase_difference_definition") != _CANONICAL_PHASE:
        raise SnowInObservationError("dswe must declare the canonical phase direction")
    _boolean_support(observation, "observation_support")
    _require_alignment(observation, "observation_support", dswe)

    for name in required_attrs:
        _text(observation.attrs[name], name)
