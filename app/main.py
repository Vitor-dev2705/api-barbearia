# app/main.py
from fastapi import FastAPI
from app.routes import router

# Aqui eu inicializo a minha API inteira, dando-lhe um título e uma descrição
app = FastAPI(
    title="API Barbearia do Futuro",
    description="Uma API estruturada em camadas com agendamento inteligente, NLP e Dashboard financeiro."
)

# Nesta linha eu pego todas as rotas que criei no meu ficheiro 'routes' e conecto ao motor principal
app.include_router(router)

@app.get("/")
def raiz_do_sistema():
    """Eu criei esta rota base apenas para eu entrar no navegador e saber que o servidor está a correr bem."""
    return {"status": "Online", "mensagem": "A API da Barbearia foi iniciada com sucesso!"}