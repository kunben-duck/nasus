package com.autotest.platform.repository;

import com.autotest.platform.entity.User;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface UserRepository extends JpaRepository<User, Long> {
    
    Optional<User> findByUsername(String username);
    
    Optional<User> findByEmail(String email);
    
    boolean existsByUsername(String username);
    
    boolean existsByEmail(String email);
    
    @Query("SELECT u FROM User u WHERE u.status = :status")
    Page<User> findByStatus(@Param("status") User.UserStatus status, Pageable pageable);
    
    @Query("SELECT u FROM User u WHERE u.role = :role")
    Page<User> findByRole(@Param("role") User.UserRole role, Pageable pageable);
    
    @Query("SELECT u FROM User u WHERE u.username LIKE %:keyword% OR u.email LIKE %:keyword% OR u.fullName LIKE %:keyword%")
    Page<User> searchUsers(@Param("keyword") String keyword, Pageable pageable);
    
    long countByStatus(User.UserStatus status);
}
