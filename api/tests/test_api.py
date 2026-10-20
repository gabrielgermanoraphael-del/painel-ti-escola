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

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.limite import limite_ip  # noqa: E402
from app.models import Chamado, Usuario, agora  # noqa: E402
from app.security import gerar_hash  # noqa: E402

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
            db.commit()

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
        r = self.cli.post("/chamados", json={"sala": "3", "tipo": "projetor", "detalhe": "  Liga mas   não dá imagem "})
        self.assertEqual(r.status_code, 201, r.text)
        d = r.json()
        self.assertEqual((d["local"], d["tipo_nome"], d["duplicado"]), ("Sala 3", "Projetor", False))
        self.assertEqual(len(ENVIADOS), 1)
        self.assertEqual(ENVIADOS[0][0], "Sala 3: Projetor")
        self.assertEqual(ENVIADOS[0][1], "Liga mas não dá imagem")

    def test_codigos_dos_qr_impressos(self):
        for sala, nome in [("Sala 13 (IPP)", "Sala 13 (IPP)"), ("Coordenação", "Coordenação"),
                           ("professores", "Sala dos Professores"), ("SECRETARIA", "Secretaria"), ("11", "Sala 11")]:
            r = self.cli.post("/chamados", json={"sala": sala, "tipo": "internet"})
            self.assertEqual(r.status_code, 201, (sala, r.text))
            self.assertEqual(r.json()["local"], nome)

    def test_sala_inexistente_e_tipo_invalido(self):
        self.assertEqual(self.cli.post("/chamados", json={"sala": "99", "tipo": "som"}).status_code, 404)
        self.assertEqual(self.cli.post("/chamados", json={"sala": "1", "tipo": "cafe"}).status_code, 422)
        self.assertEqual(self.cli.post("/chamados", json={"sala": "1", "tipo": "som", "detalhe": "x" * 301}).status_code, 422)
        self.assertEqual(ENVIADOS, [])

    def test_duplicado_nao_notifica_de_novo(self):
        a = self.cli.post("/chamados", json={"sala": "2", "tipo": "som"}).json()
        b = self.cli.post("/chamados", json={"sala": "2", "tipo": "som"})
        self.assertEqual(b.status_code, 201)
        self.assertTrue(b.json()["duplicado"])
        self.assertEqual(a["id"], b.json()["id"])
        self.assertEqual(len(ENVIADOS), 1)
        # tipo diferente na mesma sala é outro chamado
        self.assertFalse(self.cli.post("/chamados", json={"sala": "2", "tipo": "lousa"}).json()["duplicado"])

    def test_limite_por_ip(self):
        cods = ["internet", "chave", "lousa", "projetor", "computador", "som", "tablet", "impressora", "outro"]
        res = [self.cli.post("/chamados", json={"sala": str(1 + i % 8), "tipo": cods[i % 9]}).status_code
               for i in range(12)]
        self.assertEqual(res.count(201), 10)
        self.assertEqual(res[-1], 429)

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

    def test_senha_errada(self):
        r = self.cli.post("/auth/login", json={"usuario": "gabriel", "senha": "errada"})
        self.assertEqual(r.status_code, 401)

    def test_tecnico_nao_administra(self):
        h = self.token("tec", "senha-forte-2")
        self.assertEqual(self.cli.post("/locais", json={"codigo": "14", "nome": "Sala 14"}, headers=h).status_code, 403)
        self.assertEqual(self.cli.post("/usuarios", json={"usuario": "x1", "nome": "X", "senha": "12345678"},
                                       headers=h).status_code, 403)

    # ---------------- fluxo completo do TI
    def test_fluxo_atender_resolver_reabrir(self):
        h = self.token()
        id_ = self.cli.post("/chamados", json={"sala": "5", "tipo": "lousa", "detalhe": "caneta não funciona"}).json()["id"]
        abertos = self.cli.get("/chamados", params={"status": ["aberto", "atendimento"]}, headers=h).json()
        self.assertEqual([c["id"] for c in abertos], [id_])

        c = self.cli.post(f"/chamados/{id_}/atender", headers=h).json()
        self.assertEqual((c["status"], c["atendido_por"]), ("atendimento", "Gabriel"))
        self.assertIsNotNone(c["atendido_em"])

        c = self.cli.post(f"/chamados/{id_}/resolver", json={"solucao": "Calibrei o PointWrite"}, headers=h).json()
        self.assertEqual((c["status"], c["solucao"]), ("resolvido", "Calibrei o PointWrite"))
        self.assertTrue(c["resolvido_em"].endswith(("+00:00", "Z")))

        self.assertEqual(self.cli.post(f"/chamados/{id_}/atender", headers=h).status_code, 409)
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
        self.cli.post("/chamados", json={"sala": "1", "tipo": "som"})
        so_secretaria = self.cli.get("/chamados", params={"local_id": locais["Secretaria"]}, headers=h).json()
        self.assertEqual([c["local"] for c in so_secretaria], ["Secretaria"])
        self.assertEqual(self.cli.get("/chamados", params={"status": "xyz"}, headers=h).status_code, 422)

    def test_estatisticas(self):
        h = self.token()
        ids = [self.cli.post("/chamados", json={"sala": s, "tipo": t}).json()["id"]
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
        self.assertEqual(self.cli.post("/chamados", json={"sala": "14", "tipo": "som"}).status_code, 201)
        self.assertEqual(self.cli.post("/locais", json={"codigo": "14", "nome": "X"}, headers=h).status_code, 409)
        # desativar o local bloqueia novos chamados
        self.cli.patch(f"/locais/{r.json()['id']}", json={"ativo": False}, headers=h)
        self.assertEqual(self.cli.post("/chamados", json={"sala": "14", "tipo": "lousa"}).status_code, 404)

        r = self.cli.post("/usuarios", json={"usuario": "Maria", "nome": "Maria", "senha": "outra-senha-9"}, headers=h)
        self.assertEqual(r.status_code, 201)
        self.token("maria", "outra-senha-9")
        self.assertEqual(self.cli.post("/usuarios", json={"usuario": "maria", "nome": "M", "senha": "12345678"},
                                       headers=h).status_code, 409)


if __name__ == "__main__":
    unittest.main()
