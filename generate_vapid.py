from py_vapid import Vapid01
from cryptography.hazmat.primitives import serialization

def main() -> None:
    # Generate a fresh VAPID key pair before attempting to read key material.
    vapid = Vapid01()
    vapid.generate_keys()

    private_key = vapid.private_pem().decode("utf-8")
    public_key = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    ).hex()

    print("VAPID PRIVATE KEY:\n")
    print(private_key)

    print("\nVAPID PUBLIC KEY:\n")
    print(public_key)


if __name__ == "__main__":
    main()