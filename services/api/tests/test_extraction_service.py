from financial_slides_api.services import NativeExtractionService


def test_native_extraction_is_callable_from_application_service_layer() -> None:
    result = NativeExtractionService().extract_text("Operating margin reached 18%.")

    assert result.document["schemaVersion"] == "0.1"
    assert result.document["source"]["inputType"] == "text"
    assert result.telemetry.route == "pasted_text"
    assert result.telemetry.external_cost_usd == 0
