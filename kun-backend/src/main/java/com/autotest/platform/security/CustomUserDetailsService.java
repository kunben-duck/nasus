package com.autotest.platform.security;

import com.autotest.platform.entity.User;
import com.autotest.platform.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
@RequiredArgsConstructor
public class CustomUserDetailsService implements UserDetailsService {
    
    private final UserRepository userRepository;
    
    @Override
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        User user = userRepository.findByUsername(username)
                .orElseThrow(() -> new UsernameNotFoundException("User not found: " + username));
        
        if (user.getStatus() != User.UserStatus.ACTIVE) {
            throw new UsernameNotFoundException("User account is not active: " + username);
        }

        List<SimpleGrantedAuthority> authorities = new ArrayList<>();
        User.UserRole role = user.getRole() == null ? User.UserRole.OPERATIONS_ADMIN : user.getRole();
        authorities.add(new SimpleGrantedAuthority("ROLE_" + role.name()));
        if (role.canonical() != role) {
            authorities.add(new SimpleGrantedAuthority("ROLE_" + role.canonical().name()));
        }

        return new org.springframework.security.core.userdetails.User(
                user.getUsername(),
                user.getPassword(),
                authorities
        );
    }
}
