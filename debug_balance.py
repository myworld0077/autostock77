"""output1/output2 raw 구조 전체 확인"""
from core.api import api
from config.settings import settings
import json

tr_id = 'VTTC8434R' if settings.is_paper else 'TTTC8434R'
params = {
    'CANO': settings.account_prefix,
    'ACNT_PRDT_CD': settings.account_suffix,
    'AFHR_FLPR_YN': 'N',
    'OFL_YN': '',
    'INQR_DVSN': '02',
    'UNPR_DVSN': '01',
    'FUND_STTL_ICLD_YN': 'N',
    'FNCG_AMT_AUTO_RDPT_YN': 'N',
    'PRCS_DVSN': '01',
    'CTX_AREA_FK100': '',
    'CTX_AREA_NK100': '',
}

data = api.get('/uapi/domestic-stock/v1/trading/inquire-balance', tr_id, params)

print("=== 최상위 키 ===")
for k, v in data.items():
    if k not in ('output1', 'output2'):
        print(f"  {k}: {v}")

print(f"\n=== output1 길이: {len(data.get('output1', []))} ===")
print(f"=== output2 길이: {len(data.get('output2', []))} ===")

if data.get('output2'):
    print("\n=== output2[0] 전체 ===")
    print(json.dumps(data['output2'][0], ensure_ascii=False, indent=2))
else:
    print("\noutput2 비어있음 - output1 확인:")
    if data.get('output1'):
        print(json.dumps(data['output1'][0], ensure_ascii=False, indent=2))
    print("\n=== 전체 응답 키 ===")
    print(json.dumps({k: v for k, v in data.items() if k not in ('output1', 'output2')}, ensure_ascii=False, indent=2))
