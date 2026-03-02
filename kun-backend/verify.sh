#!/bin/bash

# AutoTest Platform - API Verification Script

set -e

BASE_URL="http://localhost:8080/api"
TOKEN=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

# Check if server is running
check_server() {
    log_info "Checking if server is running..."
    if ! curl -s "$BASE_URL/actuator/health" > /dev/null; then
        log_error "Server is not running. Please start the server first."
        exit 1
    fi
    log_success "Server is running"
}

# Test public endpoints
test_public_endpoints() {
    log_info "Testing public endpoints..."
    
    # Health check
    response=$(curl -s "$BASE_URL/actuator/health")
    if echo "$response" | grep -q "UP"; then
        log_success "Health check"
    else
        log_error "Health check"
    fi
    
    # Dashboard
    response=$(curl -s "$BASE_URL/dashboard")
    if echo "$response" | grep -q "success"; then
        log_success "Dashboard API"
    else
        log_error "Dashboard API"
    fi
    
    # Dashboard statistics
    response=$(curl -s "$BASE_URL/dashboard/statistics")
    if echo "$response" | grep -q "success"; then
        log_success "Dashboard Statistics API"
    else
        log_error "Dashboard Statistics API"
    fi
}

# Test authentication
test_auth() {
    log_info "Testing authentication..."
    
    # Login
    response=$(curl -s -X POST "$BASE_URL/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"admin123"}')
    
    if echo "$response" | grep -q "accessToken"; then
        TOKEN=$(echo "$response" | grep -o '"accessToken":"[^"]*' | cut -d'"' -f4)
        log_success "Login API"
    else
        log_error "Login API"
        exit 1
    fi
}

# Test protected endpoints
test_protected_endpoints() {
    log_info "Testing protected endpoints..."
    
    # Get current user
    response=$(curl -s "$BASE_URL/auth/me" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "username"; then
        log_success "Get current user API"
    else
        log_error "Get current user API"
    fi
    
    # User stories
    response=$(curl -s "$BASE_URL/user-stories" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "success"; then
        log_success "User Stories API"
    else
        log_error "User Stories API"
    fi
    
    # Test cases
    response=$(curl -s "$BASE_URL/test-cases" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "success"; then
        log_success "Test Cases API"
    else
        log_error "Test Cases API"
    fi
    
    # Test scripts
    response=$(curl -s "$BASE_URL/test-scripts" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "success"; then
        log_success "Test Scripts API"
    else
        log_error "Test Scripts API"
    fi
    
    # Executions
    response=$(curl -s "$BASE_URL/executions" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "success"; then
        log_success "Executions API"
    else
        log_error "Executions API"
    fi
    
    # Users
    response=$(curl -s "$BASE_URL/users" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "success"; then
        log_success "Users API"
    else
        log_error "Users API"
    fi
}

# Test statistics endpoints
test_statistics() {
    log_info "Testing statistics endpoints..."
    
    # Test case stats
    response=$(curl -s "$BASE_URL/test-cases/stats" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "total"; then
        log_success "Test Case Stats API"
    else
        log_error "Test Case Stats API"
    fi
    
    # Script stats
    response=$(curl -s "$BASE_URL/test-scripts/stats" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "total"; then
        log_success "Script Stats API"
    else
        log_error "Script Stats API"
    fi
    
    # Execution stats
    response=$(curl -s "$BASE_URL/executions/stats" \
        -H "Authorization: Bearer $TOKEN")
    if echo "$response" | grep -q "total"; then
        log_success "Execution Stats API"
    else
        log_error "Execution Stats API"
    fi
}

# Main function
main() {
    echo "========================================"
    echo "  AutoTest Platform - API Verification"
    echo "========================================"
    echo ""
    
    check_server
    test_public_endpoints
    test_auth
    test_protected_endpoints
    test_statistics
    
    echo ""
    echo "========================================"
    echo "  Verification Complete!"
    echo "========================================"
}

main "$@"
