import asyncio, os, sys, tempfile, inspect
import cyrrus
from cyrrus.memory import MemoryVault

LIMIT = 5
CASES = [
 # (name, facts{key:value}, [(query, needed_keys, forbidden_values)])
 ("multi_fact_6", {"user_name":"Alice","user_city":"I live in Porto","user_job":"I work as a nurse",
   "user_pet":"my cat is named Miso","user_hobby":"I enjoy climbing","user_language":"I speak Portuguese"},
  [("tell me about myself", ["user_name","user_city","user_job","user_pet","user_hobby","user_language"], []),
   ("what do you know about me", ["user_name","user_city","user_job","user_pet","user_hobby","user_language"], []),
   ("what is my name", ["user_name"], []), ("where do I live", ["user_city"], []),
   ("what is my job", ["user_job"], [])]),
 ("small3_common", {"project_name":"the Atlas project","project_deadline":"the project is due friday","project_owner":"the project owner is Sam"},
  [("what is the project deadline", ["project_deadline"], []), ("who owns the project", ["project_owner"], []),
   ("what is the project", ["project_name"], [])]),
 ("small5_common", {"project_name":"the Atlas project","project_deadline":"the project is due friday","project_owner":"the project owner is Sam",
   "project_budget":"the project budget is 5000","project_status":"the project is blocked"},
  [("what is the project budget", ["project_budget"], []), ("what is the project status", ["project_status"], []),
   ("who owns the project", ["project_owner"], [])]),
 ("small10_common", {f"project_{k}":f"the project {k} is {v}" for k,v in
   [("name","atlas"),("deadline","friday"),("owner","sam"),("budget","5000"),("status","blocked"),("repo","github"),
    ("stack","python"),("client","acme"),("risk","high"),("phase","beta")]},
  [("what is the project deadline", ["project_deadline"], []), ("what is the project risk", ["project_risk"], []),
   ("what is the project phase", ["project_phase"], []), ("summarize my project", [f"project_{k}" for k in
    ["name","deadline","owner","budget","status"]], [])]),
 ("multi_need_3", {"travel_destination":"Rome","travel_dates":"June 3 to June 10","travel_budget":"2000 euros","user_name":"Alice","user_pet":"a dog"},
  [("plan my trip to Rome in June within my budget", ["travel_destination","travel_dates","travel_budget"], []),
   ("how much can I spend on the trip", ["travel_budget"], [])]),
 ("updated_with_lookalikes", {"user_city":"Lisbon","friend_city":"my friend lives in a city called Madrid","cousin_city":"my cousin lives in a city called Paris"},
  [("which city do I live in", ["user_city"], [])]),
 ("only_common_term", {"pref_color":"I like the color blue","pref_food":"I like pizza","pref_music":"I like jazz","pref_sport":"I like tennis"},
  [("what do I like", ["pref_color","pref_food","pref_music","pref_sport"], []), ("what food do I like", ["pref_food"], [])]),
]

async def run(kwargs):
    out = {}
    for name, facts, qs in CASES:
        d = tempfile.mkdtemp(); v = MemoryVault(db_path=os.path.join(d,"h.db"), **kwargs)
        for k, val in facts.items():
            await v.upsert("s", k, val, 8)
        if name == "updated_with_lookalikes":
            await v.upsert("s", "user_city", "Porto", 8)
        for q, need, forb in qs:
            sl = await v.retrieve("s", q, limit=LIMIT)
            got = [s.id[4:] if s.id.startswith("mem_") else s.id for s in sl]
            tok = sum(len(s.content.split()) for s in sl)
            if name == "updated_with_lookalikes": need_ok = ["user_city"]
            rec = sum(1 for k in need if k in got) / len(need)
            out[(name, q)] = (rec, len(got), tok, got)
    return out

def main():
    kw = {}
    sig = inspect.signature(MemoryVault.__init__).parameters
    for a in sys.argv[1:]:
        k, v = a.split("="); 
        if k in sig: kw[k] = float(v)
    r = asyncio.run(run(kw))
    print(f"# {cyrrus.__file__}  kwargs={kw}  (v8-only params present: {'min_relative_score' in sig})")
    tot = 0; n = 0
    for (name, q), (rec, ng, tok, got) in r.items():
        print(f"{name:24s} rec={rec:.2f} n={ng} tok={tok:3d}  {q!r:50s} -> {got}")
        tot += rec; n += 1
    print(f"MEAN_RECALL={tot/n:.3f}")
main()
