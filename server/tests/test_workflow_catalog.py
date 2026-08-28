from app.workflow_catalog import DEFAULT_WORKFLOW_KEY, WORKFLOW_CATALOG


def by_key(key):
    return next(item for item in WORKFLOW_CATALOG if item["key"] == key)


def test_catalog_contains_server_owned_post_ids_and_corrected_outputs():
    assert DEFAULT_WORKFLOW_KEY == "person_replace"
    assert by_key("person_replace")["post_id"] == "2087949278193995777"
    assert by_key("person_replace")["spec"]["outputs"][0]["node_id"] == "119"
    person_replace = by_key("person_replace")
    assert person_replace["inputs"][0] == {
        "key": "upload_background", "label": "上传替换背景",
        "media_type": "image", "input_type": "boolean", "default": True,
    }
    assert person_replace["inputs"][1]["required"] is False
    assert person_replace["inputs"][1]["required_when"] == {
        "key": "upload_background", "equals": True,
    }
    assert person_replace["spec"]["uploads"][0]["required"] is False
    assert person_replace["spec"]["widgets"][0] == {
        "key": "upload_background", "node_id": "250",
        "widget": "RGTHREE_TOGGLE_AND_NAV", "label": "上传替换背景",
        "true_value": True, "false_value": False, "required": True,
        "default": True,
        "interaction": "rgthree_toggle",
    }
    assert by_key("scail_seven_outfit")["spec"]["outputs"][0]["node_id"] == "670"
    ootd = by_key("ootd_7day")
    assert [item["key"] for item in ootd["inputs"]] == [
        *[
            key
            for day in range(1, 8)
            for key in (f"day{day}", f"prompt{day}")
        ],
        "audio",
    ]
    assert ootd["spec"]["texts"] == [
        {
            "key": f"prompt{day}", "node_id": str(node_id),
            "widget": "text", "label": f"第 {day} 天动作提示词",
            "required": True,
        }
        for day, node_id in enumerate(
            (7583, 7614, 7645, 7676, 7707, 7819, 7855), 1
        )
    ]
    scail_multi = by_key("scail_multi_reference")
    assert [item["key"] for item in scail_multi["inputs"]] == [
        "motion_video", "reference1", "reference2",
    ]
    assert [item["node_id"] for item in scail_multi["spec"]["uploads"]] == [
        "214", "1166", "1244",
    ]
    assert scail_multi["spec"]["node_modes"] == [
        *[
            {"node_id": str(node_id), "mode": 2,
             "label": f"参考图节点 {node_id}"}
            for node_id in (1336, 1337, 1338, 1339)
        ],
        *[
            {"node_id": str(node_id), "mode": 4,
             "label": f"图片拼接节点 {node_id}"}
            for node_id in (1340, 1341, 1342, 1343)
        ],
    ]
    assert by_key("qwen_prompt_image")["spec"]["outputs"][0]["node_id"] == "161"
    detail_restore = by_key("hd_restore_detail_v2")
    assert detail_restore["name"] == "高定版高清修复【去AI感加细节】洗图"
    assert detail_restore["primary_input"] == "source"
    assert detail_restore["spec"]["uploads"][0]["node_id"] == "105"
    assert detail_restore["spec"]["outputs"][0]["node_id"] == "149"
    assert by_key("krea2_realistic_4k")["spec"]["texts"][0]["node_id"] == "64"
    assert by_key("krea2_realistic_4k")["spec"]["outputs"][0]["node_id"] == "83"
    assert by_key("minimax_h3_dual_stage")["spec"]["uploads"][0]["node_id"] == "137"
    assert by_key("minimax_h3_dual_stage")["inputs"][1]["input_type"] == "text"
    assert by_key("minimax_h3_dual_stage")["spec"]["texts"][0] == {
        "key": "prompt", "node_id": "138", "widget": "value",
        "label": "提示词", "required": True,
    }
    assert by_key("minimax_h3_dual_stage")["spec"]["outputs"][0]["node_id"] == "168"
    assert by_key("seedvr2_upscale")["spec"]["uploads"][0]["node_id"] == "15"
    assert by_key("seedvr2_upscale")["spec"]["outputs"][0]["node_id"] == "101"
    assert by_key("minimax_h3_four_view")["spec"]["uploads"][0]["node_id"] == "17"
    assert by_key("minimax_h3_four_view")["spec"]["outputs"][0]["node_id"] == "5"
    assert by_key("auto_storyboard_short_video")["spec"]["uploads"][0]["node_id"] == "41"
    assert by_key("auto_storyboard_short_video")["spec"]["texts"][0] == {
        "key": "request", "node_id": "127", "widget": "text",
        "label": "分镜数量与要求", "required": True,
    }
    assert by_key("auto_storyboard_short_video")["spec"]["outputs"][0]["node_id"] == "114"
    assert by_key("auto_storyboard_short_video")["spec"]["outputs"][0]["menu_actions"] == [
        "save preview", "save image",
    ]
    assert (
        by_key("auto_storyboard_short_video")["spec"]["outputs"][0]["menu_actions"]
        == by_key("qwen_multi_view")["spec"]["outputs"][0]["menu_actions"]
    )
    assert [item["node_id"] for item in by_key("firered_ecommerce_tryon")["spec"]["uploads"]] == ["207", "208"]
    assert by_key("firered_ecommerce_tryon")["inputs"][2]["input_type"] == "text"
    assert by_key("firered_ecommerce_tryon")["spec"]["texts"][0] == {
        "key": "prompt", "node_id": "264", "widget": "编辑文本",
        "label": "换装要求", "required": True,
    }
    assert by_key("firered_ecommerce_tryon")["spec"]["outputs"][0]["node_id"] == "253"
    assert [item["node_id"] for item in by_key("ltx23_hd_digital_human")["spec"]["uploads"]] == ["517", "607"]
    assert by_key("ltx23_hd_digital_human")["spec"]["outputs"][0]["node_id"] == "140"
    assert by_key("scail_4k_pose_background")["inputs"][2]["input_type"] == "text"
    assert by_key("scail_4k_pose_background")["spec"]["texts"][0] == {
        "key": "prompt", "node_id": "424", "widget": "编辑文本",
        "label": "迁移要求", "required": True,
    }


def test_all_catalog_entries_have_runnable_server_configuration():
    assert len(WORKFLOW_CATALOG) == 16
    assert not any(item["key"] == "qwen_tryon" for item in WORKFLOW_CATALOG)
    for item in WORKFLOW_CATALOG:
        assert item["post_id"].isdigit()
        assert item["inputs"]
        assert item["spec"]["outputs"]


def test_frontend_workflow_descriptions():
    assert by_key("firered_ecommerce_tryon")["description"] == (
        "让图1的人物穿上图2人物身上的衣服，不要改变发型，头发保持长发"
    )
    assert by_key("scail_4k_pose_background")["description"] == (
        "将图1中的角色移至图2中，并调整为与图2角色相似的姿势。"
        "保持图1角色的外貌特征一致性，重新进行光线处理，使其与图2场景的光线和整体氛围自然融合，"
        "确保无明显人工痕迹。"
    )
    assert by_key("auto_storyboard_short_video")["description"] == "12，包含一个手部特写"


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
        "hd_restore_detail_v2": "2087951445663510530",
        "scail_seven_outfit": "2087947462567874561",
        "ootd_7day": "2087951298946752514",
        "minimax_h3_dual_stage": "2089228867037913090",
        "person_replace": "2087949278193995777",
        "scail_4k_pose_background": "2088160851734913026",
        "krea2_realistic_4k": "2088149025097863170",
        "seedvr2_upscale": "2089614562243993601",
    }
    assert {item["key"]: item["post_id"] for item in WORKFLOW_CATALOG} == expected
