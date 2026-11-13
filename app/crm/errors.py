"""Error de reglas del CRM con el código HTTP que le corresponde. Módulo puro (sin SQLAlchemy) para que la lógica pura de las piezas también lo use."""


class CrmError(Exception):
    """Error de reglas del CRM con el código HTTP que le corresponde (el router lo convierte en respuesta)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status
