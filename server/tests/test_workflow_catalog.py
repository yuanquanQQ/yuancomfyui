from app.workflow_catalog import DEFAULT_WORKFLOW_KEY, WORKFLOW_CATALOG


def by_key(key):
    return next(item for item in WORKFLOW_CATALOG if item["key"] == key)


def test_catalog_contains_server_owned_post_ids_and_corrected_outputs():
    assert DEFAULT_WORKFLOW_KEY == "person_replace"
    assert by_key("person_replace")["post_id"] == "2087949278193995777"
    assert by_key("person_replace")["spec"]["outputs"][0]["node_id"] == "119"
    assert by_key("scail_seven_outfit")["spec"]["outputs"][0]["node_id"] == "670"
    assert by_key("qwen_prompt_image")["spec"]["outputs"][0]["node_id"] == "161"
    assert by_key("krea2_realistic_4k")["spec"]["texts"][0]["node_id"] == "64"
    assert by_key("krea2_realistic_4k")["spec"]["outputs"][0]["node_id"] == "83"
    assert by_key("minimax_h3_dual_stage")["spec"]["uploads"][0]["node_id"] == "137"
    assert by_key("minimax_h3_dual_stage")["spec"]["outputs"][0]["node_id"] == "168"
    assert by_key("seedvr2_upscale")["spec"]["uploads"][0]["node_id"] == "15"
    assert by_key("seedvr2_upscale")["spec"]["outputs"][0]["node_id"] == "101"
    assert by_key("minimax_h3_four_view")["spec"]["uploads"][0]["node_id"] == "17"
    assert by_key("minimax_h3_four_view")["spec"]["outputs"][0]["node_id"] == "5"
    assert by_key("auto_storyboard_short_video")["spec"]["uploads"][0]["node_id"] == "41"
    assert by_key("auto_storyboard_short_video")["spec"]["texts"][0]["node_id"] == "127"
    assert by_key("auto_storyboard_short_video")["spec"]["outputs"][0]["node_id"] == "114"
    assert [item["node_id"] for item in by_key("firered_ecommerce_tryon")["spec"]["uploads"]] == ["207", "208"]
    assert by_key("firered_ecommerce_tryon")["spec"]["outputs"][0]["node_id"] == "253"
    assert [item["node_id"] for item in by_key("ltx23_hd_digital_human")["spec"]["uploads"]] == ["517", "607"]
    assert by_key("ltx23_hd_digital_human")["spec"]["outputs"][0]["node_id"] == "140"


def test_all_catalog_entries_have_runnable_server_configuration():
    assert len(WORKFLOW_CATALOG) == 16
    assert not any(item["key"] == "qwen_tryon" for item in WORKFLOW_CATALOG)
    for item in WORKFLOW_CATALOG:
        assert item["post_id"].isdigit()
        assert item["inputs"]
        assert item["spec"]["outputs"]


def test_catalog_post_mapping():
    expected = {
        "animate_transfer": "2087936157744189442",
        "scail_multi_reference": "2087945522677108738",
        "qwen_multi_view": "2087934940880134146",
        "auto_storyboard_short_video": "2089754761372454913",
        "firered_ecommerce_tryon": "2089732224055861249",
        "ltx23_hd_digital_human": "2089711917068804098",
        "minimax_h3_four_view": "2089783285118496770",
        "qwen_prompt_image": "2087933748502417409",
        "hd_restore": "2087951445663510530",
        "scail_seven_outfit": "2087947462567874561",
        "ootd_7day": "2087951298946752514",
        "minimax_h3_dual_stage": "2089228867037913090",
        "person_replace": "2087949278193995777",
        "scail_4k_pose_background": "2088160851734913026",
        "krea2_realistic_4k": "2088149025097863170",
        "seedvr2_upscale": "2089614562243993601",
    }
    assert {item["key"]: item["post_id"] for item in WORKFLOW_CATALOG} == expected
