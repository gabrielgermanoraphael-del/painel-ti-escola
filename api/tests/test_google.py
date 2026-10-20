"""Login dos professores com Google e liberação pelo TI.

Os tokens do Google são simulados: geramos uma chave RSA só para o teste e assinamos
tokens com o mesmo formato que o Google envia. A API confere tudo como em produção.
"""
import time
import unittest
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from tests import test_api as base  # configura o ambiente de teste antes de importar a API
from app import google_auth, main
from app.models import Pessoa

SessionLocal = base.SessionLocal

CLIENT_ID = "123-teste.apps.googleusercontent.com"
DOMINIO = "educ.indaiatuba.sp.gov.br"
CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OUTRA_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class JWKSFalso:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=CHAVE.public_key())


def token_google(chave=CHAVE, alg="RS256", **mudar):
    agora = int(time.time())
    dados = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1000001",
             "email": f"carla.souza@{DOMINIO}", "email_verified": True, "hd": DOMINIO,
             "name": "Carla Souza", "picture": "https://lh3.googleusercontent.com/a/x",
             "iat": agora, "exp": agora + 3600}
    dados.update(mudar)
    dados = {k: v for k, v in dados.items() if v is not None}
    return jwt.encode(dados, chave, algorithm=alg, headers={"kid": "teste"})


class TesteGoogle(base.TesteAPI):
    """Herda o setUp (banco limpo, usuários do TI); os testes da classe-mãe não rodam de novo aqui."""

    def setUp(self):
        super().setUp()
        google_auth._cliente_jwks = JWKSFalso()

    def tearDown(self):
        google_auth._cliente_jwks = None
        main.config.GOOGLE_CLIENT_ID = CLIENT_ID
        super().tearDown()

    def entrar(self, **mudar):
        return self.cli.post("/auth/google", json={"credential": token_google(**mudar)})

    def h(self, sessao):
        return {"Authorization": "Bearer " + sessao["access_token"]}

    # ------------------------------------------------ login
    def test_primeiro_login_fica_pendente_com_codigo(self):
        r = self.entrar()
        self.assertEqual(r.status_code, 200, r.text)
        p = r.json()["pessoa"]
        self.assertEqual((p["nome"], p["email"], p["status"], p["salas"]), ("Carla Souza", f"carla.souza@{DOMINIO}",
                                                                           "pendente", []))
        self.assertRegex(p["codigo"], r"^[A-HJ-NP-Z2-9]{3}-[A-HJ-NP-Z2-9]{3}$")
        # entrar de novo mantém o mesmo código e atualiza o nome
        r2 = self.entrar(name="Carla S. Souza").json()["pessoa"]
        self.assertEqual((r2["codigo"], r2["nome"]), (p["codigo"], "Carla S. Souza"))
        self.assertEqual(self.cli.get("/professor/eu", headers=self.h(r.json())).json()["status"], "pendente")

    def test_config_publica(self):
        self.assertEqual(self.cli.get("/config/publica").json(), {"google_client_id": CLIENT_ID, "dominio": DOMINIO})

    def test_so_aceita_o_dominio_institucional(self):
        casos = [
            dict(email="carla@gmail.com", hd=None),                      # conta pessoal
            dict(email="carla@outra.sp.gov.br", hd="outra.sp.gov.br"),    # outro domínio Workspace
            dict(email="carla@gmail.com"),                                # hd certo, e-mail não
            dict(email=f"carla@x{DOMINIO}", hd=DOMINIO),                  # sufixo parecido
            dict(email_verified=False),
        ]
        for mudar in casos:
            r = self.entrar(**mudar)
            self.assertEqual(r.status_code, 403, (mudar, r.text))
        with SessionLocal() as db:
            self.assertEqual(db.query(Pessoa).count(), 1)  # só a professora criada no setUp

    def test_rejeita_tokens_falsos(self):
        agora = int(time.time())
        casos = {
            "outro aplicativo": dict(aud="999-outro.apps.googleusercontent.com"),
            "emissor falso": dict(iss="https://falso.com"),
            "vencido": dict(exp=agora - 3600, iat=agora - 7200),
            "sem sub": dict(sub=None),
        }
        for nome, mudar in casos.items():
            self.assertEqual(self.entrar(**mudar).status_code, 401, nome)
        # assinado por outra chave (não é do Google)
        r = self.cli.post("/auth/google", json={"credential": token_google(chave=OUTRA_CHAVE)})
        self.assertEqual(r.status_code, 401)
        # assinado com o segredo HS256 da própria API (ataque de troca de algoritmo)
        falso = token_google(chave=main.config.JWT_SECRET, alg="HS256")
        self.assertEqual(self.cli.post("/auth/google", json={"credential": falso}).status_code, 401)
        self.assertEqual(self.cli.post("/auth/google", json={"credential": "x" * 30}).status_code, 401)

    def test_sem_client_id_configurado(self):
        main.config.GOOGLE_CLIENT_ID = ""
        self.assertEqual(self.entrar().status_code, 503)

    # ------------------------------------------------ liberação pelo TI
    def test_fluxo_codigo_liberacao_e_salas(self):
        sessao = self.entrar().json()
        prof = self.h(sessao)
        codigo = sessao["pessoa"]["codigo"]

        # pendente: não abre chamado e a mensagem traz o código
        r = self.abrir({"sala": "3", "tipo": "projetor"}, prof)
        self.assertEqual(r.status_code, 403)
        self.assertIn(codigo, r.json()["detail"])

        # técnico (não precisa ser admin) acha pelo código, digitado de qualquer jeito
        ti = self.token("tec", "senha-forte-2")
        achado = self.cli.get(f"/pessoas/codigo/{codigo.replace('-', '').lower()}", headers=ti)
        self.assertEqual(achado.status_code, 200, achado.text)
        pid = achado.json()["id"]
        self.assertEqual(self.cli.get("/pessoas/codigo/ZZZ-ZZZ", headers=ti).status_code, 404)
        self.assertIn(pid, [p["id"] for p in self.cli.get("/pessoas", params={"status": "pendente"}, headers=ti).json()])

        # libera só as salas 3 e 5
        locais = {l["codigo"]: l["id"] for l in self.cli.get("/locais", headers=ti).json()}
        r = self.cli.put(f"/pessoas/{pid}/acesso", json={"status": "ativo", "salas": [locais["3"], locais["5"]]},
                         headers=ti)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([s["nome"] for s in r.json()["salas"]], ["Sala 3", "Sala 5"])
        self.assertEqual(r.json()["liberado_por"], "Técnico")

        eu = self.cli.get("/professor/eu", headers=prof).json()
        self.assertEqual((eu["status"], [s["codigo"] for s in eu["salas"]]), ("ativo", ["3", "5"]))

        self.assertEqual(self.abrir({"sala": "3", "tipo": "projetor"}, prof).status_code, 201)
        self.assertEqual(self.abrir({"sala": "5", "tipo": "lousa"}, prof).status_code, 201)
        r = self.abrir({"sala": "4", "tipo": "som"}, prof)
        self.assertEqual(r.status_code, 403)
        self.assertIn("Sala 4", r.json()["detail"])

        # o TI vê quem abriu
        lista = self.cli.get("/chamados", headers=ti).json()
        self.assertEqual({c["aberto_por"] for c in lista}, {"Carla Souza"})

        # bloquear corta o acesso na hora (o token continua válido, mas não abre chamado)
        self.cli.put(f"/pessoas/{pid}/acesso", json={"status": "bloqueado", "salas": []}, headers=ti)
        r = self.abrir({"sala": "3", "tipo": "som"}, prof)
        self.assertEqual(r.status_code, 403)
        self.assertIn("bloqueado", r.json()["detail"])
        # e o bloqueio continua depois de entrar de novo
        self.assertEqual(self.entrar().json()["pessoa"]["status"], "bloqueado")

    def test_validacoes_da_liberacao(self):
        pid = self.entrar().json()
        ti = self.token()
        with SessionLocal() as db:
            pid = db.query(Pessoa).filter_by(google_sub="1000001").one().id
        url = f"/pessoas/{pid}/acesso"
        self.assertEqual(self.cli.put(url, json={"status": "ativo", "salas": []}, headers=ti).status_code, 422)
        self.assertEqual(self.cli.put(url, json={"status": "ativo", "salas": [9999]}, headers=ti).status_code, 422)
        self.assertEqual(self.cli.put(url, json={"status": "dono", "todas_salas": True}, headers=ti).status_code, 422)
        self.assertEqual(self.cli.put("/pessoas/9999/acesso", json={"status": "ativo", "todas_salas": True},
                                      headers=ti).status_code, 404)
        r = self.cli.put(url, json={"status": "ativo", "todas_salas": True}, headers=ti)
        self.assertEqual((r.status_code, r.json()["todas_salas"]), (200, True))

    def test_conta_google_recriada_com_mesmo_email_volta_a_pendente(self):
        self.entrar()
        ti = self.token()
        with SessionLocal() as db:
            pid = db.query(Pessoa).filter_by(google_sub="1000001").one().id
        self.cli.put(f"/pessoas/{pid}/acesso", json={"status": "ativo", "todas_salas": True}, headers=ti)
        p = self.entrar(sub="2000002").json()["pessoa"]
        self.assertEqual(p["status"], "pendente")
        with SessionLocal() as db:
            self.assertEqual(db.query(Pessoa).filter_by(email=f"carla.souza@{DOMINIO}").count(), 1)


# Não repetir os testes herdados de TesteAPI dentro desta classe
for _nome in [n for n in dir(base.TesteAPI) if n.startswith("test_")]:
    if _nome not in TesteGoogle.__dict__:
        setattr(TesteGoogle, _nome, None)

if __name__ == "__main__":
    unittest.main()
