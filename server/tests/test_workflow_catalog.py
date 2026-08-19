from app.workflow_catalog import DEFAULT_WORKFLOW_KEY, WORKFLOW_CATALOG


def by_key(key):
    return next(item for item in WORKFLOW_CATALOG if item["key"] == key)


def test_catalog_contains_server_owned_workflow_ids_and_corrected_outputs():
    assert DEFAULT_WORKFLOW_KEY == "person_replace"
    assert by_key("person_replace")["workflow_id"] == "2089624864981344257"
    assert by_key("person_replace")["spec"]["outputs"][0]["node_id"] == "119"
    assert by_key("scail_seven_outfit")["spec"]["outputs"][0]["node_id"] == "670"
    assert by_key("qwen_prompt_image")["spec"]["outputs"][0]["node_id"] == "161"
    assert by_key("krea2_realistic_4k")["spec"]["texts"][0]["node_id"] == "64"
    assert by_key("krea2_realistic_4k")["spec"]["outputs"][0]["node_id"] == "83"
    assert by_key("minimax_h3_dual_stage")["spec"]["uploads"][0]["node_id"] == "137"
    assert by_key("minimax_h3_dual_stage")["spec"]["outputs"][0]["node_id"] == "168"
    assert by_key("seedvr2_upscale")["spec"]["uploads"][0]["node_id"] == "15"
    assert by_key("seedvr2_upscale")["spec"]["outputs"][0]["node_id"] == "101"


def test_all_catalog_entries_have_runnable_server_configuration():
    assert len(WORKFLOW_CATALOG) == 13
    for item in WORKFLOW_CATALOG:
        assert item["workflow_id"].isdigit()
        assert item["inputs"]
        assert item["spec"]["outputs"]
