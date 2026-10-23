CREATE TABLE IF NOT EXISTS `estudiantes` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `documento` varchar(20) NOT NULL,
  `nombre` varchar(100) NOT NULL,
  `grado` varchar(20) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `documento` (`documento`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `usuarios` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `documento` varchar(20) NOT NULL,
  `nombre` varchar(100) NOT NULL,
  `password` varchar(255) NOT NULL,
  `rol` varchar(50) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `documento` (`documento`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `llegadas_tardes` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `estudiante_id` int(11) NOT NULL,
  `trae_justificacion` varchar(10) NOT NULL,
  `motivo` text DEFAULT NULL,
  `registrado_por` varchar(100) DEFAULT NULL,
  `registrado_por_rol` varchar(50) DEFAULT NULL,
  `fecha` date DEFAULT curdate(),
  `hora` time DEFAULT curtime(),
  PRIMARY KEY (`id`),
  KEY `estudiante_id` (`estudiante_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `padres_estudiantes` (
  `padre_id` int(11) NOT NULL,
  `estudiante_id` int(11) NOT NULL,
  PRIMARY KEY (`padre_id`, `estudiante_id`),
  KEY `estudiante_id` (`estudiante_id`),
  CONSTRAINT `fk_padres_estudiantes_padre`
    FOREIGN KEY (`padre_id`) REFERENCES `usuarios` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_padres_estudiantes_estudiante`
    FOREIGN KEY (`estudiante_id`) REFERENCES `estudiantes` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
