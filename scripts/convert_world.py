import json
from pathlib import Path
import yaml

def convert():
    yaml_path = Path("worlds/dnd_5e_forgotten_realms.yaml")
    json_path = Path("worlds/dnd_5e_forgotten_realms.json")
    
    if not yaml_path.exists():
        print(f"Error: {yaml_path} does not exist.")
        return False
        
    print(f"Reading {yaml_path}...")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        
    # Inject starting_story
    data["starting_story"] = {
        "title": "凡達林礦坑的危機 (The Phandalin Crisis)",
        "prologue": "費倫大陸的凡達林，原本是一個偏遠而平靜的開拓小鎮。然而，最近紅印幫的匪徒活動日益猖獗，鎮民生活在恐懼之中。更神祕的是，傳說中失落已久的波濤迴音洞窟（Wave Echo Cave）似乎有了線索，Gundren Rockseeker 帶著他的秘密計畫回到了這裡，卻在運送補給的途中神祕失蹤。危機四伏的冒險即將展開，你是要挺身而出對抗紅印幫，還是揭開失落礦坑背後的巨大陰謀？"
    }
    
    # Write to JSON
    print(f"Writing {json_path}...")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print("Conversion complete!")
    return True

if __name__ == "__main__":
    convert()
