"""Contract-only examples; values and provenance below are synthetic."""

import pytest
import xarray as xr

from nisar_isnobal_da.observations.snowin_adapter import (
    SnowInObservationError,
    adapt_snowin_observation,
    validate_da_observation,
)


def _synthetic_snowin_pair() -> xr.Dataset:
    dswe = xr.DataArray(
        [[0.01, 0.02], [0.03, float("nan")]],
        dims=("y", "x"),
        coords={"y": [0.0, 1.0], "x": [0.0, 1.0]},
        name="dswe",
        attrs={
            "quantity": "pairwise_dSWE",
            "units": "m",
            "phase_difference_definition": "secondary_minus_reference",
            "wavelength_m": 1.0,
            "retrieval_method": "synthetic_fixture",
            "phase_reference_method": "synthetic_fixture",
            "grid_mapping": "spatial_ref",
        },
    )
    dswe.coords["y"].attrs["units"] = "m"
    dswe.coords["x"].attrs["units"] = "m"
    return xr.Dataset(
        {
            "dswe": dswe,
            "pairwise_supported": (
                ("y", "x"),
                [[True, True], [True, False]],
            ),
            "spatial_ref": xr.DataArray(
                0, attrs={"spatial_ref": "LOCAL_SYNTHETIC_TEST_CRS"}
            ),
        },
        attrs={
            "snowin_schema_version": "synthetic-fixture-v1",
            "product_kind": "pairwise_interferogram",
            "temporal_edge": "reference_to_secondary",
            "phase_difference_definition": "secondary_minus_reference",
            "source_phase_difference_definition": "secondary_minus_reference",
            "phase_transform": "identity",
            "reference_time": "2026-01-01T00:00:00Z",
            "secondary_time": "2026-01-13T00:00:00Z",
            "wavelength_m": 1.0,
            "source_granule_id": "SYNTHETIC-NOT-A-CMR-PRODUCT",
            "phase_reference_method": "synthetic_fixture",
        },
    )


def test_synthetic_snowin_pair_passes_adapter_without_filling_da_fields():
    pair = _synthetic_snowin_pair()

    observation = adapt_snowin_observation(
        pair,
        processing_maturity="SYNTHETIC",
        processing_crid="SYNTHETIC-CRID",
        processing_product_version="synthetic-product-version",
        processing_collection_version="synthetic-collection-version",
    )

    assert observation["dswe"].equals(pair["dswe"])
    assert observation["observation_support"].values.tolist() == [
        [True, True],
        [True, False],
    ]
    assert observation.attrs["reference_method"] == "synthetic_fixture"
    assert pair.attrs.get("processing_maturity") is None

    with pytest.raises(SnowInObservationError, match="DA observation is incomplete"):
        validate_da_observation(observation)


def test_serialized_support_flags_round_trip_as_boolean(tmp_path):
    pair = _synthetic_snowin_pair()
    pair["pairwise_supported"] = pair["pairwise_supported"].astype("uint8")
    pair["pairwise_supported"].attrs.update(
        {
            "flag_values": [0, 1],
            "flag_meanings": "unsupported supported",
        }
    )
    path = tmp_path / "snowin_pair.nc"
    pair.to_netcdf(path, engine="h5netcdf")

    with xr.open_dataset(path, engine="h5netcdf") as saved:
        observation = adapt_snowin_observation(
            saved.load(),
            processing_maturity="SYNTHETIC",
            processing_crid="SYNTHETIC-CRID",
            processing_product_version="synthetic-product-version",
            processing_collection_version="synthetic-collection-version",
        )

    assert observation["observation_support"].dtype.kind == "b"
    assert observation["observation_support"].values.tolist() == [
        [True, True],
        [True, False],
    ]


def test_serialized_support_flags_reject_nonbinary_values():
    pair = _synthetic_snowin_pair()
    pair["pairwise_supported"] = pair["pairwise_supported"].astype("uint8")
    pair["pairwise_supported"].values[0, 0] = 2
    pair["pairwise_supported"].attrs.update(
        {
            "flag_values": [0, 1],
            "flag_meanings": "unsupported supported",
        }
    )

    with pytest.raises(SnowInObservationError, match="explicitly encoded 0/1"):
        adapt_snowin_observation(
            pair,
            processing_maturity="SYNTHETIC",
            processing_crid="SYNTHETIC-CRID",
            processing_product_version="synthetic-product-version",
            processing_collection_version="synthetic-collection-version",
        )
