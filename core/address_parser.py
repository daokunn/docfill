"""
地址离线解析模块
使用本地省市区字典（data/region_dict.json）将地址文本拆分为：
省、市、区/县、详细地址。
不调用任何网络 API。
"""

import json
import os
from typing import Dict, Optional

from app_paths import data_path

# 省市区字典：优先读取 exe 同目录 data/region_dict.json（可外置自定义），否则使用 exe 内置资源
REGION_DICT_FILE = data_path("region_dict.json")


class AddressParser:
    """地址解析器"""

    def __init__(self, dict_path: str = REGION_DICT_FILE):
        """加载省市区字典，默认使用 data/region_dict.json"""
        self.region_dict = self._load_dict(dict_path)  # {省: {市: [区, ...]}}

    @staticmethod
    def _load_dict(path: str) -> Dict:
        """加载省市区字典，过滤掉以 _ 开头的说明性键，文件损坏返回空字典"""
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 去掉说明性键
            return {k: v for k, v in data.items() if not k.startswith("_")}
        except (json.JSONDecodeError, IOError):
            return {}

    def parse(self, address: str) -> Dict[str, str]:
        """
        解析地址文本。
        :return: {"省": ..., "市": ..., "区": ..., "详细地址": ...}
        解析失败时，省/市/区为空，详细地址为完整原始文本（降级策略）。
        """
        result = {"省": "", "市": "", "区": "", "详细地址": address or ""}
        if not address or not self.region_dict:
            return result

        addr = address.strip()

        # 1. 匹配省
        province = self._match_province(addr)
        if province:
            result["省"] = province
            # 从地址中移除省名，继续匹配市
            addr = addr.replace(province, "", 1)

        # 2. 匹配市
        city = self._match_city(addr, province)
        if city:
            result["市"] = city
            addr = addr.replace(city, "", 1)

        # 3. 匹配区/县
        district = self._match_district(addr, province, city)
        if district:
            result["区"] = district
            addr = addr.replace(district, "", 1)

        # 剩余部分作为详细地址
        detail = addr.strip(" ，,。.")
        result["详细地址"] = detail if detail else (address or "")

        return result

    def _match_province(self, text: str) -> Optional[str]:
        """匹配省份名称（支持省略"省"字）"""
        for prov in self.region_dict.keys():
            # 尝试完整匹配（带"省"）和省略"省"的匹配
            prov_short = prov.replace("省", "")
            if prov in text:
                return prov
            if prov_short and prov_short in text:
                # 确认省略省字的匹配不会误匹配（例如"江西"匹配"江西省"）
                return prov
        return None

    def _match_city(self, text: str, province: Optional[str]) -> Optional[str]:
        """匹配城市名称"""
        cities = {}
        if province and province in self.region_dict:
            cities = self.region_dict[province]
        else:
            # 未匹配到省，搜索所有市
            for prov, city_dict in self.region_dict.items():
                for city in city_dict.keys():
                    cities[city] = prov

        for city in cities.keys():
            city_short = city.replace("市", "")
            if city in text:
                return city
            if city_short and city_short in text:
                return city
        return None

    def _match_district(self, text: str, province: Optional[str],
                        city: Optional[str]) -> Optional[str]:
        """匹配区/县名称"""
        districts = []
        if province and city and province in self.region_dict and city in self.region_dict[province]:
            districts = self.region_dict[province][city]
        elif city:
            # 未匹配到省，搜索所有市下的区
            for prov, city_dict in self.region_dict.items():
                if city in city_dict:
                    districts = city_dict[city]
                    break

        for dist in districts:
            dist_short = dist.replace("区", "").replace("县", "").replace("市", "")
            if dist in text:
                return dist
            if dist_short and len(dist_short) >= 2 and dist_short in text:
                return dist
        return None
