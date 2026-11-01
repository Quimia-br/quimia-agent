"""Executa chamadas de tools antes da síntese estruturada, com limite de passos."""
import asyncio
import contextvars
import json
from concurrent.futures import ThreadPoolExecutor
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.agent.contracts import Evidence


class ToolAgent:
    def __init__(self, model, tools, prompt, output_schema, max_steps=6):
        self.model = model
        self.tools = {item.name: item for item in tools}
        self.prompt = prompt
        self.schema = output_schema
        self.max_steps = max_steps

    def _run_tool(self, call):
        selected = self.tools.get(call['name'])
        try:
            return selected.invoke(call['args']) if selected else {
                'status': 'error', 'message': 'Tool não autorizada.'}
        except Exception:
            return {'status': 'error', 'message': 'Parâmetros inválidos ou consulta indisponível.'}

    def _run_tools(self, calls):
        """Resultados na ordem das chamadas. As de uma mesma rodada são independentes e rodam juntas: cada uma é uma
        ida ao banco, e em série o tempo delas se somava."""
        if len(calls) == 1:
            return [self._run_tool(calls[0])]
        with ThreadPoolExecutor(max_workers=min(len(calls), 4)) as pool:
            futures = [pool.submit(contextvars.copy_context().run, self._run_tool, call) for call in calls]
            return [future.result() for future in futures]

    def invoke(self, payload):
        result, _ = self.invoke_with_evidence(payload)
        return result

    def invoke_with_evidence(self, payload):
        messages = [SystemMessage(content=self.prompt + "\nNesta etapa, use as tools disponíveis para obter os dados. "
                    "A síntese JSON será feita depois. Não responda com fatos antes das consultas."),
                    HumanMessage(content=json.dumps(payload, ensure_ascii=False))]
        results = []
        bound = self.model.bind_tools(list(self.tools.values()))
        for _ in range(self.max_steps):
            response = bound.invoke(messages)
            messages.append(response)
            calls = response.tool_calls
            if not calls:
                break
            for call, result in zip(calls, self._run_tools(calls)):
                results.append({'tool': call['name'], 'resultado': result})
                messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call['id']))
        # Não aceita uma resposta intermediária como resposta final ou evidência.
        context = {**payload, 'CONTEXTO_CONFIRMADO_PELAS_TOOLS': results}
        final = self.model.with_structured_output(self.schema).invoke([
            SystemMessage(content=self.prompt + "\nNesta etapa, não chame tools. "
                          "Responda no contrato JSON usando apenas os resultados de consulta fornecidos. "
                          "Se não houver resultados suficientes, informe a ausência de dados ou peça esclarecimento."),
            HumanMessage(content=json.dumps(context, ensure_ascii=False))])
        evidence = [Evidence(source_id=f"tool:{index}:{item['tool']}", title=item['tool'],
                             content=json.dumps(item['resultado'], ensure_ascii=False))
                    for index, item in enumerate(results)
                    if item['resultado'].get('status') == 'ok']
        return self.schema.model_validate(final), evidence

    async def ainvoke(self, payload):
        return await asyncio.to_thread(self.invoke, payload)

    async def ainvoke_with_evidence(self, payload):
        return await asyncio.to_thread(self.invoke_with_evidence, payload)
