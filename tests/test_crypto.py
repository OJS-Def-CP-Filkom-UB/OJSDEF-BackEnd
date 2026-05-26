from app.services.crypto import encrypt_api_key, decrypt_api_key


def test_encrypt_decrypt_roundtrip():
    plaintext = "my-secret-api-key-1234"
    ct = encrypt_api_key(plaintext)
    assert ct != plaintext
    assert decrypt_api_key(ct) == plaintext


def test_each_encrypt_produces_unique_ciphertext():
    ct1 = encrypt_api_key("same")
    ct2 = encrypt_api_key("same")
    assert ct1 != ct2  # different nonces
