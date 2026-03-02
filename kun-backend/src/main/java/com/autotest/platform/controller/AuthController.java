package com.autotest.platform.controller;

import com.autotest.platform.dto.*;
import com.autotest.platform.entity.User;
import com.autotest.platform.repository.UserRepository;
import com.autotest.platform.security.JwtTokenProvider;
import com.autotest.platform.service.UserService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;

@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
@Slf4j
@CrossOrigin(origins = "*")
public class AuthController {
    
    private final AuthenticationManager authenticationManager;
    private final JwtTokenProvider jwtTokenProvider;
    private final UserRepository userRepository;
    private final UserService userService;
    private final PasswordEncoder passwordEncoder;
    
    @PostMapping("/login")
    public ResponseEntity<ApiResponse<LoginResponse>> login(@Valid @RequestBody LoginRequest request) {
        log.info("Login attempt for user: {}", request.getUsername());
        
        Authentication authentication = authenticationManager.authenticate(
                new UsernamePasswordAuthenticationToken(request.getUsername(), request.getPassword())
        );
        
        SecurityContextHolder.getContext().setAuthentication(authentication);
        
        String accessToken = jwtTokenProvider.generateToken(authentication);
        String refreshToken = jwtTokenProvider.generateRefreshToken(authentication);
        
        User user = userRepository.findByUsername(request.getUsername())
                .orElseThrow(() -> new RuntimeException("User not found"));
        
        user.setLastLoginAt(LocalDateTime.now());
        userRepository.save(user);
        
        UserDTO userDTO = userService.getUserByUsername(user.getUsername());
        
        LoginResponse response = LoginResponse.builder()
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .tokenType("Bearer")
                .expiresIn(jwtTokenProvider.getExpirationTime())
                .user(userDTO)
                .build();
        
        log.info("User logged in successfully: {}", request.getUsername());
        return ResponseEntity.ok(ApiResponse.success("Login successful", response));
    }
    
    @PostMapping("/register")
    @PreAuthorize("hasAnyRole('SYSTEM_ADMIN','ADMIN')")
    public ResponseEntity<ApiResponse<UserDTO>> register(@Valid @RequestBody RegisterRequest request) {
        log.info("Registration attempt for user: {}", request.getUsername());
        
        if (userRepository.existsByUsername(request.getUsername())) {
            return ResponseEntity.badRequest()
                    .body(ApiResponse.error(400, "Username already exists"));
        }
        
        if (userRepository.existsByEmail(request.getEmail())) {
            return ResponseEntity.badRequest()
                    .body(ApiResponse.error(400, "Email already exists"));
        }
        
        User user = User.builder()
                .username(request.getUsername())
                .email(request.getEmail())
                .password(passwordEncoder.encode(request.getPassword()))
                .fullName(request.getFullName())
                .role(User.UserRole.OPERATIONS_ADMIN)
                .permissions(String.join(",", User.defaultPermissionsByRole(User.UserRole.OPERATIONS_ADMIN)))
                .status(User.UserStatus.ACTIVE)
                .build();
        
        User savedUser = userRepository.save(user);
        UserDTO userDTO = userService.getUserByUsername(savedUser.getUsername());
        
        log.info("User registered successfully: {}", request.getUsername());
        return ResponseEntity.ok(ApiResponse.success("Registration successful", userDTO));
    }
    
    @PostMapping("/refresh")
    public ResponseEntity<ApiResponse<TokenRefreshResponse>> refreshToken(@RequestBody TokenRefreshRequest request) {
        String refreshToken = request.getRefreshToken();
        
        if (!jwtTokenProvider.validateToken(refreshToken)) {
            return ResponseEntity.badRequest()
                    .body(ApiResponse.error(400, "Invalid refresh token"));
        }
        
        String username = jwtTokenProvider.getUsernameFromToken(refreshToken);
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found"));
        
        String newAccessToken = jwtTokenProvider.generateTokenFromUsername(username);
        String newRefreshToken = jwtTokenProvider.generateRefreshTokenFromUsername(username);
        
        TokenRefreshResponse response = TokenRefreshResponse.builder()
                .accessToken(newAccessToken)
                .refreshToken(newRefreshToken)
                .tokenType("Bearer")
                .expiresIn(jwtTokenProvider.getExpirationTime())
                .build();
        
        return ResponseEntity.ok(ApiResponse.success("Token refreshed", response));
    }
    
    @GetMapping("/me")
    public ResponseEntity<ApiResponse<UserDTO>> getCurrentUser(Authentication authentication) {
        if (authentication == null
                || authentication.getName() == null
                || "anonymousUser".equalsIgnoreCase(authentication.getName())) {
            return ResponseEntity.status(401)
                    .body(ApiResponse.error(401, "Authentication required"));
        }

        String username = authentication.getName();
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new RuntimeException("User not found"));

        UserDTO userDTO = userService.getUserByUsername(user.getUsername());
        return ResponseEntity.ok(ApiResponse.success(userDTO));
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class RegisterRequest {
        private String username;
        private String email;
        private String password;
        private String fullName;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class TokenRefreshRequest {
        private String refreshToken;
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class TokenRefreshResponse {
        private String accessToken;
        private String refreshToken;
        private String tokenType;
        private Long expiresIn;
    }
}
