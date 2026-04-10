from app.services import processar_texto_com_ia

print("Enviando mensagem para o Gemini...")

# Simulando uma mensagem difícil
texto = "Queria dar um tapa no visual amanhã, acho que umas duas e meia da tarde fica bom pra mim."

resultado = processar_texto_com_ia(texto)

print("\n--- RESPOSTA DA API ---")
print(resultado)