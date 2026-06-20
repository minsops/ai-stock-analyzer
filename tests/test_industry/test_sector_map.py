from __future__ import annotations

from src.industry.sector_map import CSI_SECTORS, csi_sector


def test_csi_sectors_cover_ten() -> None:
    assert len(CSI_SECTORS) == 10
    assert set(CSI_SECTORS.values()) >= {"能源", "原材料", "工业", "信息技术", "金融地产", "医药卫生"}


def test_csi_sector_maps_common_industries() -> None:
    assert csi_sector("C39计算机、通信和其他电子设备制造业") == "信息技术"
    assert csi_sector("C27医药制造业") == "医药卫生"
    assert csi_sector("J66货币金融服务") == "金融地产"
    assert csi_sector("C36汽车制造业") == "可选消费"
    assert csi_sector("C32有色金属冶炼和压延加工业") == "原材料"
    assert csi_sector("D44电力、热力生产和供应业") == "公用事业"
    assert csi_sector("C35专用设备制造业") == "工业"


def test_csi_sector_handles_unknown() -> None:
    assert csi_sector(None) is None
    assert csi_sector("") is None
    # 未知制造业子类默认归工业
    assert csi_sector("C99某新型制造业") == "工业"
