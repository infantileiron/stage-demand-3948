"""Natural-key insert-only seed; never overwrites user edits."""
from datetime import date,timedelta
import logging
import math
import random
from src.utils.database import init_db,insert_row,list_rows
from src.utils.security import password_hash
from src.services.forecast import analyze

def demo_rows():
    rng=random.Random(261104)
    rows=[]
    for venue,capacity,base in (("大剧场",800,410),("黑匣子",300,142),("实验厅",500,225)):
        for i in range(420):
            day=date(2025,9,17)+timedelta(days=i)
            weekend=day.weekday()>=5
            event=int(i%31 in (8,9))
            people=base+95*weekend+65*event+i*.09+22*math.sin(i*2*math.pi/365)+rng.gauss(0,14)
            rows.append({"date":day.isoformat(),"venue":venue,"attendance":int(max(0,min(capacity,round(people)))),"capacity":capacity,"event":event})
    return rows

def seed():
    init_db()
    for role,name in (("admin","陈溪·值班主管"),("analyst","林予·排演分析"),("viewer","周末值班组")):
        insert_row("users",role+"@stage.local",{"email":role+"@stage.local","name":name,"role":role,"password_hash":password_hash("Stage2611!")},preserve=True)
    rows=demo_rows()
    dataset=insert_row("datasets","拾光剧场420天到场记录",{"name":"拾光剧场420天到场记录","filename":"attendance_daily_202611.csv","row_count":1260,"venues":["大剧场","黑匣子","实验厅"],"rows":rows},preserve=True)
    first=insert_row("scenarios","11月常规排演",{"name":"11月常规排演","dataset_id":dataset["id"],"venue":"大剧场","horizon":7,"weekend_event":False,"people_per_usher":65},preserve=True)
    blackbox=insert_row("scenarios","黑匣子周末特别场",{"name":"黑匣子周末特别场","dataset_id":dataset["id"],"venue":"黑匣子","horizon":7,"weekend_event":True,"people_per_usher":45},preserve=True)
    lab=insert_row("scenarios","实验厅常规排演",{"name":"实验厅常规排演","dataset_id":dataset["id"],"venue":"实验厅","horizon":7,"weekend_event":False,"people_per_usher":55},preserve=True)
    def completed_run(key,scenario):
        existing=next((r for r in list_rows("runs") if r["key"]==key),None)
        payload={"scenario_id":scenario["id"],"status":"completed","error":None,
            "result":existing["result"] if existing else analyze(dataset["rows"],scenario)}
        return insert_row("runs",key,payload,preserve=True)
    run=completed_run("seed-run-november",first)
    plan=insert_row("plans","11月常规场引导员草案",{"name":"11月常规场引导员草案","run_id":run["id"],"venue":"大剧场","days":run["result"]["forecast"],"status":"approved","approved_by":"admin@stage.local"},preserve=True)
    insert_row("reports","11月排演需求预演纪要",{"title":"11月排演需求预演纪要","plan_id":plan["id"],"venue":"大剧场","days":plan["days"],"status":"approved"},preserve=True)
    # Two more approved single-venue plans so the shared-pool merge has three
    # same-range sources out of the box; the drafts stay as originals.
    shared_plans=[]
    for scenario,key,plan_name,report_name in ((
        blackbox,"seed-run-blackbox","黑匣子周末特别场引导员草案","黑匣子周末特别场纪要"),(
        lab,"seed-run-lab","实验厅常规场引导员草案","实验厅常规场纪要")):
        seeded_run=completed_run(key,scenario)
        seeded_plan=insert_row("plans",plan_name,{"name":plan_name,"run_id":seeded_run["id"],"venue":scenario["venue"],"days":seeded_run["result"]["forecast"],"status":"approved","approved_by":"admin@stage.local"},preserve=True)
        insert_row("reports",report_name,{"title":report_name,"plan_id":seeded_plan["id"],"venue":scenario["venue"],"days":seeded_plan["days"],"status":"approved"},preserve=True)
        shared_plans.append(seeded_plan)
    merge_name="三厅共用引导员编排（示例）"
    if not any(row["key"]==merge_name for row in list_rows("merges")):
        try:
            from src.schemas.merge import MergeCreate
            from src.services.merge import create as create_merge
            create_merge(MergeCreate(name=merge_name,
                plan_ids=[plan["id"],*[member["id"] for member in shared_plans]],daily_capacity=18))
        except Exception:
            logging.exception("Demo shared-pool merge skipped")
    from src.services.schedule import next_occurrence,clock
    insert_row("schedules","每日08:30排演册站内报送",{"name":"每日08:30排演册站内报送","source_report_id":None,"daily_time":"08:30","enabled":True,"next_run":next_occurrence("08:30",clock()),"last_run":None,"last_error":None},preserve=True)
    return {table:len(list_rows(table)) for table in ("users","datasets","scenarios","runs","plans","reports","schedules","delivery_snapshots","merges")}

if __name__=="__main__": print(seed())
