# app/main.py
from fastapi import FastAPI
from app.routes import router

app = FastAPI(
    title="API Barbearia do Futuro",
    description="Uma API estruturada em camadas com agendamento inteligente, NLP e Dashboard financeiro."
)

app.include_router(router)

@app.get("/")
def raiz_do_sistema():
    return {"status": "Online", "mensagem": "A API da Barbearia foi iniciada com sucesso!"}