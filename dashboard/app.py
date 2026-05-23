"""
AutoStock 웹 대시보드
- 실시간 보유 종목, 잔고, 거래이력 모니터링
"""
from flask import Flask, render_template, jsonify
from config.settings import settings
from utils.logger import log

app = Flask(__name__, template_folder="templates", static_folder="static")


@app.route("/")
def index():
    """메인 대시보드"""
    return render_template("index.html",
                           trade_mode="모의투자" if settings.is_paper else "실전투자")


@app.route("/api/balance")
def api_balance():
    """잔고 API"""
    try:
        from core.account import get_balance
        return jsonify(get_balance())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/holdings")
def api_holdings():
    """보유종목 API"""
    try:
        from core.account import get_holdings
        return jsonify(get_holdings())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/price/<stock_code>")
def api_price(stock_code: str):
    """현재가 API"""
    try:
        from core.market import get_current_price
        return jsonify(get_current_price(stock_code))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def run_dashboard(host: str = "0.0.0.0", port: int = 5000):
    """대시보드 서버 실행"""
    log.info(f"🌐 대시보드 시작: http://localhost:{port}")
    app.run(host=host, port=port, debug=True)
