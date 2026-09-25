variable "REGISTRY" {
  default = ""
}

variable "RSYNC_TAG" {
  default = "1"
}

variable "JENKINS_UID" {
  default = "1000"
}

variable "JENKINS_GID" {
  default = "1000"
}

variable "NODE_VERSION" {
  default = "24.21.0"
}

variable "NODE_SHA256" {
  default = "fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6"
}

variable "NODE_TAG" {
  default = "24"
}

variable "PUBLISH_LATEST" {
  default = false
}

group "default" {
  targets = ["rsync", "node"]
}

target "_common" {
  context    = "docker/jenkins-agents"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "rsync" {
  inherits = ["_common"]
  target   = "rsync"
  args = {
    JENKINS_UID = JENKINS_UID
    JENKINS_GID = JENKINS_GID
  }
  tags = concat(
    ["${REGISTRY != "" ? "${REGISTRY}/" : ""}jenkins-agent-rsync:${RSYNC_TAG}"],
    PUBLISH_LATEST ? ["${REGISTRY != "" ? "${REGISTRY}/" : ""}jenkins-agent-rsync:latest"] : []
  )
}

target "node" {
  inherits = ["_common"]
  target   = "node"
  args = {
    NODE_VERSION = NODE_VERSION
    NODE_SHA256  = NODE_SHA256
  }
  tags = concat(
    ["${REGISTRY != "" ? "${REGISTRY}/" : ""}jenkins-agent-node:${NODE_TAG}"],
    PUBLISH_LATEST ? ["${REGISTRY != "" ? "${REGISTRY}/" : ""}jenkins-agent-node:latest"] : []
  )
}
