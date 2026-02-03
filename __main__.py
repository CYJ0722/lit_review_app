"""
运行方式: python -m lit_review_app
"""
import uvicorn
from lit_review_app.api.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
