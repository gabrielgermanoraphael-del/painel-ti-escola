"""Testes da API.  Rodar:  python -m unittest -v
Por padrão usa SQLite temporário. Para testar no PostgreSQL:
    TEST_DATABASE_URL=postgresql+psycopg://... python -m unittest -v
"""
import os
import tempfile
import unittest
from datetime import timedelta

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_tmp}/teste.db")
os.environ["JWT_SECRET"] = "segredo-de-teste-com-mais-de-32-caracteres-ok"
os.environ["NTFY_TOPIC"] = "topico-teste"
os.environ["CORS_ORIGINS"] = "https://exemplo.github.io"
os.environ["GOOGLE_CLIENT_ID"] = "123-teste.apps.googleusercontent.com"
os.environ["DOMINIO_PERMITIDO"] = "educ.indaiatuba.sp.gov.br"

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.limite import limite_ip  # noqa: E402
from app.models import Chamado, Pessoa, Usuario, agora  # noqa: E402
from app.security import criar_token_professor, gerar_hash  # noqa: E402

ENVIADOS = []
main.notificar_ntfy = lambda *a, **k: ENVIADOS.append(a) or True


class TesteAPI(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        limite_ip.limpar()
        ENVIADOS.clear()
        self.cli = TestClient(main.app)
        self.cli.__enter__()  # roda o "startup": cria tabelas e locais
        with SessionLocal() as db:
            db.add(Usuario(usuario="gabriel", nome="Gabriel", senha_hash=gerar_hash("senha-forte-1"), papel="admin"))
            db.add(Usuario(usuario="tec", nome="Técnico", senha_hash=gerar_hash("senha-forte-2"), papel="tecnico"))
            prof = Pessoa(google_sub="g-ana", email="ana@educ.indaiatuba.sp.gov.br", nome="Ana Prof",
                          codigo="AAA-AAA", status="ativo", todas_salas=True)
            db.add(prof)
            db.commit()
            self.prof = {"Authorization": "Bearer " + criar_token_professor(prof)[0]}

    def abrir(self, corpo, h=None):
        """Abre chamado pela página do QR, como um professor liberado em todas as salas."""
        return self.cli.post("/chamados", json=corpo, headers=self.prof if h is None else h)

    def tearDown(self):
        self.cli.__exit__(None, None, None)

    def token(self, usuario="gabriel", senha="senha-forte-1"):
        r = self.cli.post("/auth/login", json={"usuario": usuario, "senha": senha})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": "Bearer " + r.json()["access_token"]}

    # ---------------- público
    def test_saude(self):
        self.assertTrue(self.cli.get("/saude").json()["ok"])

    def test_abrir_chamado_e_notificar(self):
        r = self.abrir({"sala": "3", "tipo": "projetor", "detalhe": "  Liga mas   não dá imagem "})
        self.assertEqual(r.status_code, 201, r.text)
        d = r.json()
        self.assertEqual((d["local"], d["tipo_nome"], d["duplicado"]), ("Sala 3", "Projetor", False))
        self.assertEqual(len(ENVIADOS), 1)
        self.assertEqual(ENVIADOS[0][0], "Sala 3: Projetor")
        self.assertEqual(ENVIADOS[0][1], f"Liga mas não dá imagem\nAberto por Ana Prof · chamado #{d['id']}")

    def test_codigos_dos_qr_impressos(self):
        for sala, nome in [("Sala 13 (IPP)", "Sala 13 (IPP)"), ("Coordenação", "Coordenação"),
                           ("professores", "Sala dos Professores"), ("SECRETARIA", "Secretaria"), ("11", "Sala 11")]:
            r = self.abrir({"sala": sala, "tipo": "internet"})
            self.assertEqual(r.status_code, 201, (sala, r.text))
            self.assertEqual(r.json()["local"], nome)

    def test_sala_inexistente_e_tipo_invalido(self):
        self.assertEqual(self.abrir({"sala": "99", "tipo": "som"}).status_code, 404)
        self.assertEqual(self.abrir({"sala": "1", "tipo": "cafe"}).status_code, 422)
        self.assertEqual(self.abrir({"sala": "1", "tipo": "som", "detalhe": "x" * 301}).status_code, 422)
        self.assertEqual(ENVIADOS, [])

    def test_duplicado_nao_notifica_de_novo(self):
        a = self.abrir({"sala": "2", "tipo": "som"}).json()
        b = self.abrir({"sala": "2", "tipo": "som"})
        self.assertEqual(b.status_code, 201)
        self.assertTrue(b.json()["duplicado"])
        self.assertEqual(a["id"], b.json()["id"])
        self.assertEqual(len(ENVIADOS), 1)
        # tipo diferente na mesma sala é outro chamado
        self.assertFalse(self.abrir({"sala": "2", "tipo": "lousa"}).json()["duplicado"])

    def test_limite_por_professor_e_por_ip(self):
        cods = ["internet", "chave", "lousa", "projetor", "computador", "som", "tablet", "impressora", "outro"]
        res = [self.abrir({"sala": str(1 + i % 8), "tipo": cods[i % 9]}).status_code
               for i in range(12)]
        self.assertEqual(res.count(201), 10)
        self.assertEqual(res[-1], 429)
        # outro professor no mesmo IP (Wi-Fi da escola) ainda consegue, até o limite geral do IP
        with SessionLocal() as db:
            p = Pessoa(google_sub="g-bia", email="bia@educ.indaiatuba.sp.gov.br", nome="Bia", codigo="BBB-BBB",
                       status="ativo", todas_salas=True)
            db.add(p)
            db.commit()
            h = {"Authorization": "Bearer " + criar_token_professor(p)[0]}
        self.assertEqual(self.abrir({"sala": "7", "tipo": "som"}, h).status_code, 201)
        antes = main.config.LIMITE_POR_IP
        main.config.LIMITE_POR_IP = 11  # 10 da Ana + 1 da Bia já contados
        try:
            self.assertEqual(self.abrir({"sala": "8", "tipo": "som"}, h).status_code, 429)
        finally:
            main.config.LIMITE_POR_IP = antes

    def test_cors_libera_so_a_pagina(self):
        ok = self.cli.options("/chamados", headers={"Origin": "https://exemplo.github.io",
                                                    "Access-Control-Request-Method": "POST",
                                                    "Access-Control-Request-Headers": "content-type"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "https://exemplo.github.io")
        ruim = self.cli.options("/chamados", headers={"Origin": "https://malicioso.com",
                                                      "Access-Control-Request-Method": "POST"})
        self.assertNotEqual(ruim.headers.get("access-control-allow-origin"), "https://malicioso.com")

    # ---------------- segurança
    def test_rotas_do_ti_exigem_login(self):
        for rota in ["/chamados", "/estatisticas", "/locais", "/eu", "/chamados/1"]:
            self.assertEqual(self.cli.get(rota).status_code, 401, rota)
        self.assertEqual(self.cli.get("/chamados", headers={"Authorization": "Bearer lixo"}).status_code, 401)
        for rota in ["/pessoas", "/pessoas/codigo/AAA-AAA", "/usuarios"]:
            self.assertEqual(self.cli.get(rota).status_code, 401, rota)
        self.assertEqual(self.cli.put("/pessoas/1/acesso", json={"status": "ativo", "todas_salas": True}).status_code, 401)

    def test_abrir_chamado_exige_login_google(self):
        self.assertEqual(self.cli.post("/chamados", json={"sala": "3", "tipo": "som"}).status_code, 401)
        self.assertEqual(self.cli.get("/professor/eu").status_code, 401)
        self.assertEqual(ENVIADOS, [])

    def test_token_do_professor_e_do_ti_nao_se_misturam(self):
        # o professor (id 1) não entra no painel do TI, mesmo existindo o usuário id 1
        self.assertEqual(self.cli.get("/chamados", headers=self.prof).status_code, 401)
        self.assertEqual(self.cli.get("/pessoas", headers=self.prof).status_code, 401)
        # e o token do TI não serve para abrir chamado como professor
        self.assertEqual(self.abrir({"sala": "3", "tipo": "som"}, self.token()).status_code, 401)

    def test_senha_errada(self):
        r = self.cli.post("/auth/login", json={"usuario": "gabriel", "senha": "errada"})
        self.assertEqual(r.status_code, 401)

    def test_tecnico_nao_administra(self):
        h = self.token("tec", "senha-forte-2")
        self.assertEqual(self.cli.post("/locais", json={"codigo": "14", "nome": "Sala 14"}, headers=h).status_code, 403)
        self.assertEqual(self.cli.post("/usuarios", json={"usuario": "x1", "nome": "X", "senha": "12345678"},
                                       headers=h).status_code, 403)
        self.assertEqual(self.cli.get("/usuarios", headers=h).status_code, 403)
        self.assertEqual(self.cli.patch("/usuarios/2", json={"papel": "admin"}, headers=h).status_code, 403)

    # ---------------- fluxo completo do TI
    def test_fluxo_assumir_resolver_reabrir(self):
        h = self.token()
        id_ = self.abrir({"sala": "5", "tipo": "lousa", "detalhe": "caneta não funciona"}).json()["id"]
        abertos = self.cli.get("/chamados", params={"status": ["aberto", "atendimento"]}, headers=h).json()
        self.assertEqual([c["id"] for c in abertos], [id_])

        c = self.cli.post(f"/chamados/{id_}/assumir", headers=h).json()
        self.assertEqual((c["status"], c["atendido_por"]), ("atendimento", "Gabriel"))
        self.assertEqual((c["aberto_por"], c["aberto_por_email"]), ("Ana Prof", "ana@educ.indaiatuba.sp.gov.br"))
        self.assertIsNotNone(c["atendido_em"])

        c = self.cli.post(f"/chamados/{id_}/resolver", json={"solucao": "Calibrei o PointWrite"}, headers=h).json()
        self.assertEqual((c["status"], c["solucao"]), ("resolvido", "Calibrei o PointWrite"))
        self.assertTrue(c["resolvido_em"].endswith(("+00:00", "Z")))

        self.assertEqual(self.cli.post(f"/chamados/{id_}/assumir", headers=h).status_code, 409)
        c = self.cli.post(f"/chamados/{id_}/reabrir", headers=h).json()
        self.assertEqual((c["status"], c["resolvido_em"]), ("aberto", None))
        self.assertEqual(self.cli.get("/chamados/999", headers=h).status_code, 404)

    def test_chamado_manual_e_filtros(self):
        h = self.token("tec", "senha-forte-2")
        locais = {l["nome"]: l["id"] for l in self.cli.get("/locais", headers=h).json()}
        self.assertEqual(len(locais), 14)
        r = self.cli.post("/chamados/manual", json={"local_id": locais["Secretaria"], "tipo": "impressora",
                                                    "detalhe": "pausada"}, headers=h)
        self.assertEqual((r.status_code, r.json()["origem"]), (201, "manual"))
        self.assertEqual(ENVIADOS, [])  # manual não notifica (o técnico já sabe)
        self.abrir({"sala": "1", "tipo": "som"})
        so_secretaria = self.cli.get("/chamados", params={"local_id": locais["Secretaria"]}, headers=h).json()
        self.assertEqual([c["local"] for c in so_secretaria], ["Secretaria"])
        self.assertEqual(self.cli.get("/chamados", params={"status": "xyz"}, headers=h).status_code, 422)

    def test_estatisticas(self):
        h = self.token()
        ids = [self.abrir({"sala": s, "tipo": t}).json()["id"]
               for s, t in [("1", "projetor"), ("1", "som"), ("2", "projetor")]]
        # simula um chamado resolvido 30 minutos depois de aberto
        with SessionLocal() as db:
            c = db.get(Chamado, ids[0])
            c.criado_em = agora() - timedelta(minutes=30)
            c.status, c.resolvido_em = "resolvido", agora()
            db.commit()
        e = self.cli.get("/estatisticas", params={"dias": 7}, headers=h).json()
        self.assertEqual((e["total"], e["abertos"], e["resolvidos"]), (3, 2, 1))
        self.assertAlmostEqual(e["tempo_medio_resolucao_min"], 30, delta=1)
        self.assertEqual(e["por_tipo"]["Projetor"], 2)
        self.assertEqual(e["por_local"]["Sala 1"], 2)
        self.assertEqual(sum(e["por_dia"].values()), 3)

    def test_admin_cria_local_e_usuario(self):
        h = self.token()
        r = self.cli.post("/locais", json={"codigo": "14", "nome": "Sala 14"}, headers=h)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.abrir({"sala": "14", "tipo": "som"}).status_code, 201)
        self.assertEqual(self.cli.post("/locais", json={"codigo": "14", "nome": "X"}, headers=h).status_code, 409)
        # desativar o local bloqueia novos chamados
        self.cli.patch(f"/locais/{r.json()['id']}", json={"ativo": False}, headers=h)
        self.assertEqual(self.abrir({"sala": "14", "tipo": "lousa"}).status_code, 404)

        r = self.cli.post("/usuarios", json={"usuario": "Maria", "nome": "Maria", "senha": "outra-senha-9"}, headers=h)
        self.assertEqual(r.status_code, 201)
        self.token("maria", "outra-senha-9")
        self.assertEqual(self.cli.post("/usuarios", json={"usuario": "maria", "nome": "M", "senha": "12345678"},
                                       headers=h).status_code, 409)



    def test_admin_gerencia_contas_do_ti(self):
        h = self.token()
        contas = {u["usuario"]: u for u in self.cli.get("/usuarios", headers=h).json()}
        self.assertEqual(set(contas), {"gabriel", "tec"})
        tec_id, eu_id = contas["tec"]["id"], contas["gabriel"]["id"]
        # promover e depois desativar o técnico
        self.assertEqual(self.cli.patch(f"/usuarios/{tec_id}", json={"papel": "admin"}, headers=h).json()["papel"], "admin")
        self.cli.patch(f"/usuarios/{tec_id}", json={"ativo": False}, headers=h)
        self.assertEqual(self.cli.post("/auth/login", json={"usuario": "tec", "senha": "senha-forte-2"}).status_code, 401)
        # trocar senha
        self.cli.patch(f"/usuarios/{tec_id}", json={"ativo": True, "senha": "nova-senha-123"}, headers=h)
        self.token("tec", "nova-senha-123")
        # ninguém tira o próprio acesso de admin (evita ficar sem administrador)
        self.assertEqual(self.cli.patch(f"/usuarios/{eu_id}", json={"papel": "tecnico"}, headers=h).status_code, 409)
        self.assertEqual(self.cli.patch(f"/usuarios/{eu_id}", json={"ativo": False}, headers=h).status_code, 409)
        self.assertEqual(self.cli.patch("/usuarios/999", json={"ativo": False}, headers=h).status_code, 404)



    def test_controle_de_quem_assume(self):
        gabriel, tec = self.token(), self.token("tec", "senha-forte-2")
        id_ = self.abrir({"sala": "4", "tipo": "som", "detalhe": "sem som"}).json()["id"]
        ENVIADOS.clear()
        c = self.cli.post(f"/chamados/{id_}/assumir", headers=tec).json()
        self.assertEqual((c["status"], c["atendido_por"]), ("atendimento", "Técnico"))
        self.assertEqual(ENVIADOS[0][0], "✋ Técnico assumiu")  # a equipe fica sabendo
        self.assertEqual(ENVIADOS[0][1], f"Sala 4: Som · chamado #{id_}")
        # assumir de novo o próprio chamado não muda nada nem avisa de novo
        self.assertEqual(self.cli.post(f"/chamados/{id_}/assumir", headers=tec).status_code, 200)
        self.assertEqual(len(ENVIADOS), 1)
        # outro técnico não "rouba" o chamado sem querer
        r = self.cli.post(f"/chamados/{id_}/assumir", headers=gabriel)
        self.assertEqual(r.status_code, 409)
        self.assertIn("Técnico já assumiu", r.json()["detail"])
        # nem resolve o chamado de outro, a não ser administrador
        self.cli.post("/usuarios", json={"usuario": "joao", "nome": "João", "senha": "senha-do-joao"}, headers=gabriel)
        joao = self.token("joao", "senha-do-joao")
        self.assertEqual(self.cli.post(f"/chamados/{id_}/resolver", json={}, headers=joao).status_code, 409)
        # transferência explícita fica registrada
        c = self.cli.post(f"/chamados/{id_}/assumir", params={"transferir": "true"}, headers=joao).json()
        self.assertEqual(c["atendido_por"], "João")
        c = self.cli.post(f"/chamados/{id_}/resolver", json={"solucao": "Religuei a caixa"}, headers=joao).json()
        self.assertEqual(c["status"], "resolvido")
        self.assertEqual(self.cli.post(f"/chamados/{id_}/resolver", json={}, headers=joao).status_code, 409)
        # reabrir libera para qualquer um assumir
        c = self.cli.post(f"/chamados/{id_}/reabrir", headers=gabriel).json()
        self.assertEqual((c["status"], c["atendido_por"]), ("aberto", None))
        reg = self.cli.get(f"/chamados/{id_}/registro", headers=gabriel).json()
        self.assertEqual([(e["acao"], e["quem"]) for e in reg],
                         [("aberto", "Ana Prof"), ("assumido", "Técnico"), ("transferido", "João"),
                          ("resolvido", "João"), ("reaberto", "Gabriel")])
        self.assertEqual(reg[2]["detalhe"], "de Técnico para João")
        self.assertEqual(reg[3]["detalhe"], "Religuei a caixa")
        self.assertEqual(self.cli.get("/chamados/999/registro", headers=gabriel).status_code, 404)

    def test_resolver_direto_e_nome_antigo(self):
        h = self.token()
        id_ = self.abrir({"sala": "6", "tipo": "lousa"}).json()["id"]
        c = self.cli.post(f"/chamados/{id_}/resolver", json={"solucao": "Calibrei"}, headers=h).json()
        self.assertEqual((c["status"], c["atendido_por"]), ("resolvido", "Gabriel"))
        self.assertIsNotNone(c["atendido_em"])
        acoes = [e["acao"] for e in self.cli.get(f"/chamados/{id_}/registro", headers=h).json()]
        self.assertEqual(acoes, ["aberto", "assumido", "resolvido"])
        # manual também entra no registro, e /atender (painel antigo) ainda funciona
        locais = {l["nome"]: l["id"] for l in self.cli.get("/locais", headers=h).json()}
        m = self.cli.post("/chamados/manual", json={"local_id": locais["Secretaria"], "tipo": "impressora"}, headers=h).json()
        self.assertEqual(self.cli.post(f"/chamados/{m['id']}/atender", headers=h).json()["status"], "atendimento")
        self.assertEqual([e["acao"] for e in self.cli.get(f"/chamados/{m['id']}/registro", headers=h).json()],
                         ["registrado", "assumido"])


if __name__ == "__main__":
    unittest.main()
